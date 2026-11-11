from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.graph.state import AgentState, FollowupDecisionState
from app.services.session import session_store
from app.storage.repository import repository


def _load_opening_followup(user_id: str | None) -> tuple[list[dict], FollowupDecisionState]:
    memories = repository.list_pending_abnormal_emotions(user_id)
    should_followup = bool(memories)
    decision: FollowupDecisionState = {
        "should_followup": should_followup,
        "reason": "会话开启时发现待跟进的异常情绪记录。" if should_followup else "会话开启时没有待跟进的异常情绪记录。",
        "followup_type": "emotional_checkin" if should_followup else "none",
        "followup_status": "pending" if should_followup else "resolved",
    }
    return memories, decision


def opening_followup_node(state: AgentState) -> dict:
    """Resolve pending emotional follow-ups once when a conversation session opens."""
    session_id = state.get("session_id")
    user_id = state.get("user_id")
    if not session_id:
        memories, decision = _load_opening_followup(user_id)
    else:
        session_store.get_or_create(session_id, user_id=user_id, device_id=state.get("device_id"))
        memories, decision, _ = session_store.get_or_initialize_followup_context(
            session_id,
            lambda: _load_opening_followup(user_id),
        )
    return {
        "followup_memories": memories,
        "followup_decision": decision,
        "followup_used": bool(decision.get("should_followup")),
    }


def followup_node(state: AgentState) -> dict:
    """Create the current turn's emotional event after dialogue and emotion analysis."""
    emotion = state.get("emotion")
    if not emotion:
        return {"daily_report_delta": None}

    label = emotion.get("label", "unknown")
    need_followup = emotion.get("need_followup", False)
    event_id = str(uuid5(NAMESPACE_URL, f"bangbu-emotion:{state['request_id']}")) if state.get("request_id") else str(uuid4())
    occurred_at = state.get("timestamp") or int(datetime.now(timezone.utc).timestamp() * 1000)
    report_delta = {
        "user_status": label,
        "user_emotion": dict(emotion),
        "abnormal_events": [],
        "event_id": event_id,
        "occurred_at": occurred_at,
    }
    if need_followup:
        report_delta["abnormal_events"] = [{
            "event_id": event_id,
            "label": label,
            "label_cn": emotion.get("label_cn", label),
            "intensity": emotion.get("intensity", 0.0),
            "evidence": emotion.get("evidence", ""),
            "followup_status": "pending",
            "abnormal_event": emotion.get("content_summary") or emotion.get("evidence") or None,
            "occurred_at": occurred_at,
            "followup_count": 0,
            "latest_status": "pending",
            "user_response": None,
        }]
    return {"daily_report_delta": report_delta}
