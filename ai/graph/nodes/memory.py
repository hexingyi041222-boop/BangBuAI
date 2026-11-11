from datetime import datetime, timezone

from app.graph.state import AgentState
from app.services.memory import learn_user_memories, recall_user_memories
from app.services.session import session_store
from app.storage.repository import repository


def memory_recall_node(state: AgentState) -> dict:
    text = state.get("transcribed_text") or state.get("text") or ""
    return {"user_memories": recall_user_memories(state.get("user_id"), text)}


def memory_update_node(state: AgentState) -> dict:
    text = state.get("transcribed_text") or state.get("text") or ""
    decision = dict(state.get("followup_decision") or {})
    memories = state.get("followup_memories") or []
    delta = dict(state.get("daily_report_delta") or {})
    if decision.get("should_followup") and decision.get("followup_status") == "pending":
        repository.mark_emotion_events_followed(
            state.get("user_id"),
            [str(item["event_id"]) for item in memories if item.get("event_id")],
        )
        session_id = state.get("session_id")
        if session_id:
            decision = session_store.mark_followup_handled(session_id) or decision
        else:
            decision["followup_status"] = "followed"
        delta["followup_updates"] = [{
            "event_id": item["event_id"], "latest_status": "followed", "followup_count_delta": 1,
            "request_id": state.get("request_id"), "occurred_at": datetime.now(timezone.utc).isoformat(),
            "user_response": None,
        } for item in memories if item.get("event_id")]
    return {
        "memory_updates": learn_user_memories(state.get("user_id"), text),
        "followup_decision": decision,
        "daily_report_delta": delta or None,
    }
