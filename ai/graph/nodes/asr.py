from app.graph.state import AgentState
from app.services.asr import get_asr_service


def asr_node(state: AgentState) -> dict:
    """
    ASR 节点。

    文本输入直接作为转写结果；
    音频输入交给独立的 ASR 服务处理。
    """

    input_type = state.get("input_type")

    if input_type == "text":
        return {
            "transcribed_text": state.get("text") or "",
        }

    if input_type == "audio":
        audio_path = state.get("audio_url") or ""
        result = get_asr_service().recognize(state.get("audio"), audio_path=audio_path)
        # Emotion is deliberately analyzed only after the dialogue response.
        return {"transcribed_text": result.get("text", "")}

    return {
        "transcribed_text": "",
    }
