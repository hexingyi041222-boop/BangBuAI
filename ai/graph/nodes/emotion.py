from app.graph.state import AgentState, EmotionState


from app.core.config import settings
from app.core.contracts import AIServiceError
from app.services.doubao import RealDoubaoClient, call_with_retry, get_doubao_client
from app.services.emotion_records import LABELS_CN, bounded_number, normalize_content_tags, normalize_emotion_label, user_emotion_score


_LABELS_CN = LABELS_CN
_FOLLOWUP_LABELS = {"tired", "down", "anxious"}


def _normalize_emotion(value: dict, *, text: str = "", source: str = "model") -> EmotionState:
    label = normalize_emotion_label(value.get("label"))
    intensity = bounded_number(value.get("intensity"), default=0.0)
    confidence = bounded_number(value.get("confidence"), default=0.0)
    content_tags = normalize_content_tags(value.get("content_tags"))
    summary = value.get("content_summary")
    has_summary = isinstance(summary, str) and bool(summary.strip())
    need_followup = label in _FOLLOWUP_LABELS and intensity >= 0.6
    return {
        "label": label,
        "label_cn": _LABELS_CN[label],
        "intensity": intensity,
        "need_followup": need_followup,
        "followup_status": "pending" if need_followup else "resolved",
        "evidence": str(value.get("evidence", ""))[:200],
        "confidence": confidence,
        "content_tags": content_tags,
        "content_summary": summary.strip()[:80] if has_summary else text[:80],
        "summary_source": source if has_summary else "excerpt",
        "analysis_source": source,
        "emotion_score": user_emotion_score(label, intensity),
    }


def emotion_node(state: AgentState) -> dict:
    """根据 ASR 转写文本识别基础情绪。"""

    text = (state.get("transcribed_text") or "").strip()
    use_seed_mini = settings.doubao_mode == "real" or (settings.asr_mode == "real" and state.get("input_type") == "audio")
    if use_seed_mini:
        client = RealDoubaoClient() if settings.asr_mode == "real" and settings.doubao_mode == "mock" else get_doubao_client()
        recent_dialogue = (state.get("context") or {}).get("recent_dialogue", [])
        try:
            result = call_with_retry(
                lambda: client.analyze_emotion(text, recent_dialogue=recent_dialogue),
                operation_name="emotion",
            )
        except AIServiceError as exc:
            return {
                "emotion": None,
                "emotion_error": {
                    "code": exc.kind,
                    "message": "情绪分析暂不可用，对话回复仍可继续。",
                },
            }
        return {"emotion": _normalize_emotion(result, text=text)}

    result = get_doubao_client().analyze_emotion(text) if text else {"label": "calm", "intensity": 0.0}
    return {"emotion": _normalize_emotion(result, text=text, source="mock_rule")}
