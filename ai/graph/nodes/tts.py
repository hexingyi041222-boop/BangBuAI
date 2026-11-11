from __future__ import annotations

import logging

from app.core.config import settings
from app.graph.state import AgentState
from app.prompts import build_tts_instructions
from app.services.backend_tools import BackendToolError, BackendToolNotConfigured
from app.services.doubao import AIServiceError, call_with_retry, get_doubao_client
from app.services.tts import tts_receipts


logger = logging.getLogger(__name__)


def tts_node(state: AgentState) -> dict:
    """Synthesize a user-facing response and hand hardware audio to the backend."""
    text = (state.get("reply_text") or "").strip()
    if not text:
        return {}
    try:
        audio = call_with_retry(
            lambda: get_doubao_client().tts(
                text,
                request_id=state.get("request_id"),
                voice=(state.get("persona") or {}).get("voice") or settings.doubao_tts_voice or None,
                instructions=build_tts_instructions(settings.doubao_tts_voice_prompt, state.get("persona")),
            ),
            operation_name="tts",
        )
        output = {
            "reply_audio_id": audio.get("audio_id"),
            "reply_audio_url": audio.get("audio_url"),
            "reply_audio_base64": audio.get("audio_base64"),
            "reply_audio_format": audio.get("audio_format"),
        }
        if state.get("session_type") == "hardware" and audio.get("audio_id"):
            if audio.get("audio_base64") or audio.get("audio_url"):
                if not state.get("device_id"):
                    output["tts_delivery_state"] = "failed"
                    output["tts_error"] = {"code": "device_id_required", "message": "语音已生成，但缺少设备标识，无法请求后端下发。"}
                    return output
                try:
                    receipt = tts_receipts.send(audio["audio_id"], {
                        "user_id": state.get("user_id"),
                        "device_id": state.get("device_id"),
                        "audio_url": audio.get("audio_url"),
                        "audio_base64": audio.get("audio_base64"),
                        "format": audio.get("audio_format"),
                        "text": text,
                    })
                    output["tts_delivery_state"] = receipt.state.value
                except BackendToolNotConfigured:
                    logger.warning("tts_backend_unconfigured request_id=%s", state.get("request_id"))
                    output["tts_delivery_state"] = "failed"
                    output["tts_error"] = {"code": "backend_unconfigured", "message": "语音已生成，但硬件下发后端尚未接入。"}
                except BackendToolError as exc:
                    logger.warning("tts_backend_dispatch_failed request_id=%s code=%s", state.get("request_id"), exc.code)
                    output["tts_delivery_state"] = "failed"
                    output["tts_error"] = {"code": exc.code, "retryable": exc.retryable, "message": "语音已生成，但请求后端下发失败。"}
                except Exception:
                    logger.exception("tts_backend_dispatch_failed request_id=%s", state.get("request_id"))
                    output["tts_delivery_state"] = "failed"
                    output["tts_error"] = {"code": "tts_delivery_failure", "message": "语音已生成，但请求后端下发失败。"}
        return output
    except AIServiceError as exc:
        logger.warning("tts_unavailable request_id=%s kind=%s", state.get("request_id"), exc.kind)
        return {"tts_error": {"code": exc.kind, "message": "语音合成暂不可用，文字回复仍可使用。"}}
    except Exception:
        logger.exception("tts_unexpected_failure request_id=%s", state.get("request_id"))
        return {"tts_error": {"code": "tts_internal_failure", "message": "语音合成暂不可用，文字回复仍可使用。"}}
