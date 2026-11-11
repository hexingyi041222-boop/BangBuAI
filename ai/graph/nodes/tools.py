from __future__ import annotations

import re
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.graph.state import AgentState
from app.services.backend_tools import BackendToolError, BackendToolNotConfigured, get_backend_tool_client
from app.services.memory import upsert_user_memories
from app.services.tool_intents import extract_post_field_updates, parse_post_field_answer, parse_tool_intent
from app.storage.repository import repository


_POST_FIELDS = ("content", "title", "topic", "visibility")
_POST_FIELD_PROMPTS = {
    "content": "请先告诉我帖子正文。",
    "title": "这条帖子的标题是什么？",
    "topic": "这条帖子要加什么话题？没有话题可以回复“无”。",
    "visibility": "帖子可见范围选公开、好友可见，还是仅自己可见？",
}
_POST_VISIBILITY_LABELS = {"public": "公开", "friends": "好友可见", "private": "仅自己可见"}
_PERSONA_FIELDS = {"name", "gender", "personality", "mbti", "voice", "speaking_style", "relationship", "custom_keywords"}
logger = logging.getLogger(__name__)


def _action_result(tool_name: str, status: str, data: Any = None) -> dict[str, Any]:
    result: dict[str, Any] = {"tool_name": tool_name, "status": status}
    if data is not None:
        result["data"] = data
    return result


def _handled(reply_text: str, tool_result: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"tool_handled": True, "reply_text": reply_text, "tool_result": tool_result, **extra}


def _missing_post_field(payload: dict[str, Any]) -> str | None:
    for field in _POST_FIELDS:
        if field not in payload or (field != "topic" and not str(payload[field]).strip()):
            return field
    return None


def _post_summary(payload: dict[str, Any]) -> str:
    topic = payload["topic"] or "无"
    visibility = _POST_VISIBILITY_LABELS.get(payload["visibility"], payload["visibility"])
    return f"标题：{payload['title']}；正文：{payload['content']}；话题：{topic}；可见范围：{visibility}。"


def _advance_post(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    missing = _missing_post_field(payload)
    if missing:
        repository.save_pending_tool_action(user_id=user_id, action_type="posts.publish", status="collecting", payload={**payload, "awaiting_field": missing})
        return _handled(_POST_FIELD_PROMPTS[missing], _action_result("posts.publish", "collecting"))
    repository.save_pending_tool_action(user_id=user_id, action_type="posts.publish", status="awaiting_confirmation", payload=payload)
    return _handled(f"请核对这条帖子：{_post_summary(payload)}信息无误请明确回复“确认发布”，我再提交。", _action_result("posts.publish", "awaiting_confirmation"))


def _is_confirmation(text: str) -> bool:
    return bool(re.fullmatch(r"\s*(?:确认(?:发布)?|确定(?:发布)?|可以发布|发布吧|发吧|没问题|是的)\s*[。！!]?\s*", text))


def _is_cancellation(text: str) -> bool:
    return bool(re.fullmatch(r"\s*(?:取消|取消发布|不要发|别发了|不发了|算了)\s*[。！!]?\s*", text))


def _handle_pending_post(state: AgentState, pending: dict[str, Any], text: str) -> dict[str, Any] | None:
    user_id = state.get("user_id")
    if not user_id:
        return None
    if pending.get("status") == "publishing":
        return _handled("这条帖子正在提交处理中，请稍候。", _action_result("posts.publish", "publishing"))
    if _is_cancellation(text):
        if repository.delete_pending_tool_action(user_id, expected_status=pending.get("status")):
            return _handled("好的，这条帖子已取消，没有发布。", _action_result("posts.publish", "cancelled"))
        current = repository.get_pending_tool_action(user_id)
        status = current.get("status") if current else "not_pending"
        reply = "这条帖子正在提交处理中，不能再取消。" if status == "publishing" else "这条帖子已不在待取消状态。"
        return _handled(reply, _action_result("posts.publish", status))

    payload = dict(pending["payload"])
    if pending["status"] == "collecting":
        updates = extract_post_field_updates(text)
        awaiting = payload.pop("awaiting_field", None)
        if awaiting and awaiting not in updates:
            answer = parse_post_field_answer(awaiting, text)
            if answer is not None or awaiting == "topic" and re.search(r"(?:无|不加|不需要|没有)(?:话题|标签)?", text):
                updates[awaiting] = answer
        payload.update(updates)
        return _advance_post(user_id, payload)

    if pending["status"] == "awaiting_confirmation":
        if _is_confirmation(text):
            claimed = repository.claim_pending_tool_action(
                user_id=user_id,
                action_type="posts.publish",
                expected_status="awaiting_confirmation",
                new_status="publishing",
            )
            if not claimed:
                current = repository.get_pending_tool_action(user_id)
                if current and current.get("status") == "publishing":
                    return _handled("这条帖子正在提交处理中，请稍候。", _action_result("posts.publish", "publishing"))
                return _handled("这条帖子已不在待确认状态，没有重复提交。", _action_result("posts.publish", "not_pending"))
            payload = dict(claimed["payload"])
            try:
                response = get_backend_tool_client().publish_post(
                    user_id,
                    {key: payload[key] for key in _POST_FIELDS},
                    idempotency_key=payload.get("_idempotency_key") or state.get("request_id") or "",
                )
            except BackendToolNotConfigured as exc:
                repository.save_pending_tool_action(user_id=user_id, action_type="posts.publish", status="awaiting_confirmation", payload=payload)
                return _handled(
                    "帖子信息已确认，但发布接口尚未接入；内容仍保留为待发布草稿，没有发布成功。",
                    _action_result("posts.publish", "backend_unconfigured", {"message": str(exc)}),
                )
            except BackendToolError as exc:
                repository.save_pending_tool_action(user_id=user_id, action_type="posts.publish", status="awaiting_confirmation", payload=payload)
                return _handled(
                    "提交帖子失败，草稿仍保留。你可以稍后再次回复“确认发布”重试。",
                    _action_result("posts.publish", "failed", {"error": {"code": exc.code, "retryable": exc.retryable}}),
                )
            except Exception:
                repository.save_pending_tool_action(user_id=user_id, action_type="posts.publish", status="awaiting_confirmation", payload=payload)
                return _handled(
                    "提交帖子时遇到问题，草稿仍保留。你可以稍后再次回复“确认发布”重试。",
                    _action_result("posts.publish", "failed"),
                )
            repository.delete_pending_tool_action(user_id)
            return _handled("帖子已发布。", _action_result("posts.publish", "succeeded", response))

        updates = extract_post_field_updates(text)
        if updates:
            payload.update(updates)
            return _advance_post(user_id, payload)
        return None
    return None


def _execute_intent(state: AgentState, intent: dict[str, Any], source_text: str) -> dict[str, Any]:
    name = intent["name"]
    args = intent.get("arguments") or {}
    user_id = state.get("user_id")
    if name == "shopping.blocked":
        return _handled("我不能代你购物、下单或付款，但可以帮你查询已有订单信息。", _action_result(name, "blocked"))
    if not user_id:
        return _handled("这项操作需要先识别到你的用户账号，目前请求里没有 user_id。", _action_result(name, "user_required"))

    backend = get_backend_tool_client()
    try:
        if name == "pomodoro.set":
            if not args:
                return _handled("请告诉我专注时长；如果需要，也可以同时告诉我休息时长。", _action_result(name, "needs_input"))
            result = backend.set_pomodoro(user_id, focus_minutes=args.get("focus_minutes"), break_minutes=args.get("break_minutes"))
            return _handled("番茄钟设置已更新。", _action_result(name, "succeeded", result))
        if name == "pomodoro.start":
            result = backend.start_pomodoro(user_id)
            return _handled("番茄钟已开启。", _action_result(name, "succeeded", result))
        if name == "pomodoro.stop":
            result = backend.stop_pomodoro(user_id)
            interruption = None
            if state.get("session_id"):
                try:
                    interruption = repository.save_pomodoro_interruption(
                        user_id=user_id, session_id=state["session_id"],
                        request_id=f"pomodoro-stop:{state.get('request_id') or uuid4()}",
                        occurred_at=datetime.now(timezone.utc).isoformat(), reason=None,
                        pomodoro_id=str(result["pomodoro_id"]) if isinstance(result, dict) and result.get("pomodoro_id") else None,
                    )
                except Exception:
                    logger.exception("pomodoro_interruption_record_failed request_id=%s", state.get("request_id"))
            reply = "番茄钟已关闭。这次为什么中断呀？不想记录也可以说“跳过”。" if interruption else "番茄钟已关闭，但中断原因记录暂时不可用。"
            return _handled(reply, _action_result(name, "succeeded", {"backend": result, "interruption": interruption, "needs_reason": bool(interruption)}))
        if name == "pet.update":
            settings = {key: value for key, value in args.get("settings", {}).items() if key in _PERSONA_FIELDS and value not in (None, "", [])}
            if not settings:
                return _handled("可以修改桌宠的名字、性格、说话风格、关系称呼、性别或关键词。请告诉我想改成什么。", _action_result(name, "needs_input"))
            result = backend.update_pet_settings(user_id, settings)
            persona = repository.update_persona(user_id, settings)
            memory_updates = upsert_user_memories(user_id, settings, source_text)
            return _handled("桌宠设置已更新，我也会记住这些偏好。", _action_result(name, "succeeded", {"backend": result, "persona": persona}), memory_updates=memory_updates)
        if name == "orders.query":
            result = backend.query_orders(user_id, args)
            count = len(result.get("orders", [])) if isinstance(result, dict) and isinstance(result.get("orders"), list) else None
            reply = "订单查询完成，请查看订单信息。" if count is None else (f"查到 {count} 个订单，请查看订单信息。" if count else "没有查到符合条件的订单。")
            return _handled(reply, _action_result(name, "succeeded", result))
    except BackendToolNotConfigured as exc:
        return _handled("这项功能的业务接口尚未接入，目前没有执行操作。", _action_result(name, "backend_unconfigured", {"message": str(exc)}))
    except BackendToolError as exc:
        return _handled("调用业务功能失败，没有确认操作成功。请稍后重试。", _action_result(name, "failed", {"error": {"code": exc.code, "retryable": exc.retryable}}))
    except Exception:
        return _handled("调用业务功能时遇到问题，没有确认操作成功。请稍后重试。", _action_result(name, "failed"))

    if name == "posts.draft":
        payload = dict(args)
        payload["_idempotency_key"] = str(uuid4())
        return _advance_post(user_id, payload)
    return _handled("我暂时无法处理这项操作。", _action_result(name, "unsupported"))


def tool_router_node(state: AgentState) -> dict[str, Any]:
    """Route explicit supported voice commands before the general dialogue path."""
    text = (state.get("transcribed_text") or "").strip()
    user_id = state.get("user_id")
    if user_id:
        pending = repository.get_pending_tool_action(user_id)
        if pending and pending.get("action_type") == "posts.publish":
            handled = _handle_pending_post(state, pending, text)
            if handled:
                return handled

    intent = parse_tool_intent(text)
    if not intent:
        if user_id and state.get("session_id"):
            pending = repository.get_pending_pomodoro_interruption(user_id=user_id)
            if pending:
                declined = bool(re.fullmatch(r"(?:跳过|不想说|不记录|算了)[。！!]?", text))
                if declined or text.strip():
                    reason = None if declined else text.strip()[:500]
                    record = repository.answer_pomodoro_interruption(user_id=user_id, request_id=pending["request_id"], reason=reason)
                    return _handled("好的，已跳过原因记录。" if declined else "已记下这次中断原因。", _action_result("pomodoro.reason", "declined" if declined else "succeeded", record))
        return {"tool_handled": False}
    return _execute_intent(state, intent, text)
