from dataclasses import dataclass
from enum import Enum

from app.services.backend_tools import get_backend_tool_client


class TTSState(str, Enum):
    pending = "pending"
    sent = "sent"
    acked = "acked"
    retrying = "retrying"
    failed = "failed"


@dataclass
class TTSReceipt:
    audio_id: str
    state: TTSState = TTSState.pending
    attempts: int = 0


class TTSReceiptStore:
    def __init__(self) -> None:
        self.items: dict[str, TTSReceipt] = {}

    def send(self, audio_id: str, payload: dict) -> TTSReceipt:
        receipt = self.items.setdefault(audio_id, TTSReceipt(audio_id))
        receipt.attempts += 1
        try:
            get_backend_tool_client().dispatch_tts_to_device(
                user_id=payload.get("user_id"),
                device_id=payload["device_id"],
                audio_id=audio_id,
                audio_url=payload.get("audio_url"),
                audio_base64=payload.get("audio_base64"),
                audio_format=payload.get("format"),
                text=payload.get("text", ""),
                idempotency_key=audio_id,
            )
        except Exception:
            receipt.state = TTSState.failed
            raise
        receipt.state = TTSState.sent
        return receipt

    def ack(self, audio_id: str) -> TTSReceipt | None:
        receipt = self.items.get(audio_id)
        if receipt:
            receipt.state = TTSState.acked
        return receipt

    def retry(self, audio_id: str, payload: dict) -> TTSReceipt | None:
        receipt = self.items.get(audio_id)
        if not receipt or receipt.state == TTSState.acked:
            return receipt
        receipt.state = TTSState.retrying
        return self.send(audio_id, payload)


tts_receipts = TTSReceiptStore()
