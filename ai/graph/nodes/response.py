from app.graph.state import AgentState
from app.core.config import settings
from app.services.doubao import call_with_retry, get_doubao_client


def _asks_which_event(text: str) -> bool:
    """识别用户在追问“上一件事”具体指什么。"""

    normalized = (text or "").replace(" ", "")
    return any(phrase in normalized for phrase in ("什么事情", "什么事", "哪件事", "哪件事情", "指的是什么"))


def _followup_subject(memories: list[dict]) -> str:
    """取可安全展示的事件摘要，不暴露事件 ID、状态等内部字段。"""

    for item in memories:
        for key in ("content_summary", "abnormal_event", "evidence"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:80]
    return "你之前提到、让你有些不舒服的那件事"


def response_node(state: AgentState) -> dict:
    """Generate dialogue before analyzing the current utterance's emotion."""
    if settings.doubao_mode == "real":
        result = call_with_retry(
            lambda: get_doubao_client().chat(
                state.get("transcribed_text") or "",
                None,
                persona=state.get("persona"),
                context=state.get("context"),
                session_type=state.get("session_type"),
                user_memories=state.get("user_memories"),
                followup_memories=state.get("followup_memories"),
            ),
            operation_name="chat",
        )
        return {"reply_text": result.get("text", "")}

    followup_memories = state.get("followup_memories") or []
    if followup_memories and _asks_which_event(state.get("transcribed_text") or state.get("text") or ""):
        subject = _followup_subject(followup_memories)
        return {"reply_text": f"我指的是你之前提到的“{subject}”。如果我记错了，你可以再告诉我具体是哪件事。"}
    if followup_memories:
        return {"reply_text": "你前面说的那件事情解决了么？现在感觉怎么样呀？"}
    return {"reply_text": "我在认真听你说。"}
