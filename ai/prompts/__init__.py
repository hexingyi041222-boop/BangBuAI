"""集中管理发送给大模型的 Prompt。"""

from app.prompts.dialogue import (
    DIALOGUE_PROMPT_VERSION,
    DIALOGUE_SYSTEM_PROMPT,
    build_dialogue_messages,
)
from app.prompts.speech import (
    DEFAULT_TTS_VOICE_PROMPT,
    SPEECH_PROMPT_VERSION,
    build_audio_analysis_messages,
    build_text_emotion_messages,
    build_tts_instructions,
)

__all__ = [
    "DIALOGUE_PROMPT_VERSION",
    "DIALOGUE_SYSTEM_PROMPT",
    "build_dialogue_messages",
    "DEFAULT_TTS_VOICE_PROMPT",
    "SPEECH_PROMPT_VERSION",
    "build_audio_analysis_messages",
    "build_text_emotion_messages",
    "build_tts_instructions",
]
