from typing import Any, Protocol

from app.core.config import settings
from app.services.doubao import RealDoubaoClient, call_with_retry


class ASRService(Protocol):
    """ASR 服务统一接口。"""

    def transcribe_audio(self, audio_path: str) -> str:
        """将音频文件转换为文本。"""

    def recognize(self, audio: dict[str, Any] | None = None, *, audio_path: str = "") -> dict[str, Any]:
        """只转写音频；情绪分析由对话完成后的独立节点处理。"""


class MockASRService:
    """本地模拟 ASR，用于开发和测试。"""

    def transcribe_audio(self, audio_path: str) -> str:
        return (
            "这是 ASR 桩函数根据音频地址生成的转写文本。"
            f"音频地址：{audio_path}"
        )

    def recognize(self, audio: dict[str, Any] | None = None, *, audio_path: str = "") -> dict[str, Any]:
        return {"text": self.transcribe_audio(audio_path)}


class SeedASRService:
    """Seed Mini transcription adapter."""

    def recognize(self, audio: dict[str, Any] | None = None, *, audio_path: str = "") -> dict[str, Any]:
        return call_with_retry(
            lambda: RealDoubaoClient().asr(audio, audio_path=audio_path),
            operation_name="asr",
        )

    def transcribe_audio(self, audio_path: str) -> str:
        return self.recognize(audio_path=audio_path).get("text", "")


def get_asr_service() -> ASRService:
    """根据配置返回 ASR 服务实现。"""

    if settings.asr_mode == "real" or settings.doubao_mode == "real":
        return SeedASRService()

    if settings.asr_mode == "mock":
        return MockASRService()

    raise ValueError(
        f"不支持的 ASR_MODE: {settings.asr_mode}"
    )
