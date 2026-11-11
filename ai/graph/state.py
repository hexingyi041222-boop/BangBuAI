from typing import Any, Literal, TypedDict


class EmotionState(TypedDict, total=False):
    """
    对用户当前表达的情绪识别结果，不是邦布的虚拟情绪值或计分结果。
    """

    label: str
    label_cn: str
    intensity: float
    need_followup: bool
    followup_status: str
    evidence: str
    confidence: float | None
    content_tags: list[str]
    content_summary: str
    emotion_score: int
    analysis_source: str
    summary_source: str


class FollowupDecisionState(TypedDict, total=False):
    """
    会话开启时基于既有待跟进异常情绪事件形成的决定。

    它与本轮情绪分析结果分开，当前轮新事件只进入 daily_report_delta。
    """

    should_followup: bool
    reason: str
    followup_type: str
    followup_status: str


class PersonaState(TypedDict, total=False):
    """
    用户画像或邦布角色信息。

    当前保存邦布角色和用户画像信息。
    """

    name: str
    style: str
    extra: dict[str, Any]


class AgentState(TypedDict, total=False):
    """
    LangGraph 中所有节点共享的状态。

    total=False 表示字段可以暂时没有值。
    这是因为不同节点会逐步补充状态中的字段。
    """

    # =========================
    # 输入字段
    # =========================

    request_id: str
    user_id: str
    session_id: str

    input_type: Literal["audio", "text"]
    audio_url: str | None
    audio: dict[str, Any] | None
    text: str | None
    device_id: str | None
    session_type: Literal["hardware", "app"] | None
    timestamp: int | None
    context: dict[str, Any] | None

    # =========================
    # 中间产物
    # =========================

    transcribed_text: str | None
    emotion: EmotionState | None
    emotion_error: dict[str, Any] | None
    pending_followups: list[dict[str, Any]]
    followup_decision: FollowupDecisionState | None
    persona: PersonaState | None
    user_memories: list[dict[str, Any]]
    followup_memories: list[dict[str, Any]]
    memory_updates: list[dict[str, Any]]
    tool_handled: bool
    tool_result: dict[str, Any] | None
    bangbu_emotion: dict[str, Any] | None

    # =========================
    # 输出字段
    # =========================

    reply_text: str | None
    reply_audio_url: str | None
    reply_audio_base64: str | None
    reply_audio_id: str | None
    reply_audio_format: str | None
    tts_error: dict[str, Any] | None
    tts_delivery_state: str | None
    daily_report_delta: dict[str, Any] | None
    fallback_used: bool
    followup_used: bool
    latency_ms: int
    error: str | None
