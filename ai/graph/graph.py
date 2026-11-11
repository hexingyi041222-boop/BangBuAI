from langgraph.graph import END, START, StateGraph

from app.graph.nodes.asr import asr_node
from app.graph.nodes.emotion import emotion_node
from app.graph.nodes.response import response_node
from app.graph.nodes.followup import followup_node, opening_followup_node
from app.graph.nodes.memory import memory_recall_node, memory_update_node
from app.graph.nodes.tools import tool_router_node
from app.graph.nodes.tts import tts_node
from app.services.session import session_store
from app.services.failure_counter import failure_counter
from app.core.contracts import AIServiceError
from app.graph.state import AgentState


def build_graph():
    """构建当前版本的 LangGraph。"""

    builder = StateGraph(AgentState)

    builder.add_node("asr", asr_node)
    builder.add_node("tool_router", tool_router_node)
    builder.add_node("opening_followup", opening_followup_node)
    builder.add_node("tts", tts_node)
    builder.add_node("emotion", emotion_node)
    builder.add_node("response", response_node)
    builder.add_node("memory_recall", memory_recall_node)
    builder.add_node("memory_update", memory_update_node)
    builder.add_node("followup", followup_node)

    builder.add_edge(START, "asr")
    builder.add_edge("asr", "opening_followup")
    builder.add_edge("opening_followup", "tool_router")
    builder.add_conditional_edges(
        "tool_router",
        lambda state: "tts" if state.get("tool_handled") else "memory_recall",
    )
    builder.add_edge("memory_recall", "response")
    builder.add_edge("response", "tts")
    builder.add_edge("tts", "emotion")
    builder.add_edge("emotion", "followup")
    builder.add_conditional_edges(
        "followup",
        lambda state: END if state.get("tool_handled") else "memory_update",
    )
    builder.add_edge("memory_update", END)

    return builder.compile()


def build_emotion_graph():
    """Build the side-effect-free ASR and emotion analysis workflow."""
    builder = StateGraph(AgentState)
    builder.add_node("asr", asr_node)
    builder.add_node("emotion", emotion_node)
    builder.add_edge(START, "asr")
    builder.add_edge("asr", "emotion")
    builder.add_edge("emotion", END)
    return builder.compile()


agent_graph = build_graph()
emotion_graph = build_emotion_graph()

def invoke_graph(state: dict) -> dict:
    session_id = state.get("session_id")
    if session_id:
        session_store.get_or_create(session_id, user_id=state.get("user_id"), device_id=state.get("device_id"))
        current = session_store.status(session_id)
        if current and current.state in {"silent", "ended"}:
            return {**state, "error": {"code": "session_not_active", "message": f"会话状态为 {current.state}", "retryable": False}, "fallback_used": True}
        session_store.touch(session_id)
    try:
        result = agent_graph.invoke(state)
        if session_id:
            session_store.reset_failure(session_id)
            failure_counter.clear(session_id)
        return result
    except (AIServiceError, TimeoutError, RuntimeError) as exc:
        count = failure_counter.increment_failure(session_id) if session_id else 1
        if session_id:
            session_store.increment_failure(session_id)
        return {**state, "transcribed_text": state.get("text") or "", "reply_text": "抱歉，我暂时没有处理好这条消息，请稍后再试。", "fallback_used": True, "error": {"code": getattr(exc, "kind", "ai_internal_failure"), "message": str(exc), "retryable": getattr(exc, "retryable", True), "failure_count": count}}
