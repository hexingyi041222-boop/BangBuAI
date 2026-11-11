from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from app.core.config import settings
from app.core.contracts import AIServiceError, AITimeoutError, AI_VERSIONS
from app.prompts import (
    build_audio_analysis_messages,
    build_dialogue_messages,
    build_text_emotion_messages,
)
from app.services.emotion_records import normalize_emotion_label, rule_content_metadata


class DoubaoClient(Protocol):
    def asr(self, audio: dict[str, Any] | None = None, *, audio_path: str = "") -> dict[str, Any]: ...
    def analyze_emotion(self, text: str, *, recent_dialogue: list[dict[str, Any]] | None = None) -> dict[str, Any]: ...
    def summarize_day(self, summary: dict, persona: dict) -> str: ...
    def chat(
        self,
        text: str,
        emotion: dict[str, Any] | None = None,
        *,
        persona: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        session_type: str | None = None,
        user_memories: list[dict[str, Any]] | None = None,
        followup_memories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...
    def tts(
        self,
        text: str,
        *,
        request_id: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]: ...


class MockDoubaoClient:
    def summarize_day(self, summary: dict, persona: dict) -> str:
        return summary.get("daily_message") or "谢谢你今天愿意和我分享。"

    def asr(self, audio: dict[str, Any] | None = None, *, audio_path: str = "") -> dict[str, Any]:
        return {"text": f"这是 ASR 桩函数根据音频地址生成的转写文本。音频地址：{audio_path}", **AI_VERSIONS}

    def analyze_emotion(self, text: str) -> dict[str, Any]:
        return {"label": "calm", "label_cn": "平静", "intensity": 0.0, "confidence": 0.0, "evidence": "", **rule_content_metadata(text), **AI_VERSIONS}

    def chat(
        self,
        text: str,
        emotion: dict[str, Any] | None = None,
        *,
        persona: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        session_type: str | None = None,
        user_memories: list[dict[str, Any]] | None = None,
        followup_memories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        label = normalize_emotion_label((emotion or {}).get("label"))
        responses = {"tired": "听起来你今天有些累，先好好休息一下吧。", "down": "听起来你现在有些低落，我在这里陪你慢慢说。", "calm": "我在认真听你说。", "happy": "很高兴听到你今天心情不错！", "anxious": "听起来你有些不安，我们可以一步一步来。"}
        return {"text": responses.get(label, responses["calm"]), "ai_identity_notice": settings.ai_identity_notice, **AI_VERSIONS}

    def tts(
        self,
        text: str,
        *,
        request_id: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        return {"audio_id": request_id or f"mock-audio-{int(time.time() * 1000)}", "audio_url": settings.fallback_audio_url or None, "audio_base64": None, **AI_VERSIONS}


class RealDoubaoClient:
    def summarize_day(self, summary: dict, persona: dict) -> str:
        from app.prompts.daily_message import build_daily_message_messages

        return self._chat_completion(
            build_daily_message_messages(summary, persona),
            model=settings.doubao_emotion_model,
            temperature=0.3,
            max_tokens=256,
        )

    def _endpoint(self, path: str) -> str:
        base_url = (settings.volcengine_api_base_url.strip() or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        suffix = path.strip("/")
        return base_url if base_url.endswith(f"/{suffix}") else f"{base_url}/{suffix}"

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        if not settings.volcengine_api_key:
            raise AIServiceError("缺少 VOLCENGINE_API_KEY", kind="provider_configuration_error", retryable=False)
        return {
            "Authorization": f"Bearer {settings.volcengine_api_key}",
            "Content-Type": "application/json",
            "Accept": accept,
        }

    def _post(self, path: str, payload: dict[str, Any], *, accept: str = "application/json") -> tuple[bytes, str]:
        request = Request(
            self._endpoint(path),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(accept),
            method="POST",
        )
        try:
            with urlopen(request, timeout=max(1.0, settings.ai_timeout_ms / 1000)) as response:
                return response.read(), response.headers.get("Content-Type", "")
        except HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            raise AIServiceError(
                f"Volcengine API HTTP {exc.code}",
                kind="provider_request_error",
                retryable=retryable,
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise AITimeoutError("Volcengine API 请求超时") from exc
            raise AIServiceError(f"Volcengine API 网络请求失败: {exc.reason}", kind="provider_network_error", retryable=True) from exc
        except (TimeoutError, OSError) as exc:
            if isinstance(exc, TimeoutError):
                raise AITimeoutError("Volcengine API 请求超时") from exc
            raise AIServiceError(f"Volcengine API 网络请求失败: {exc}", kind="provider_network_error", retryable=True) from exc

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        raw, _ = self._post(path, payload)
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIServiceError("Volcengine API 返回的 JSON 格式无效", kind="provider_invalid_response", retryable=True) from exc
        if not isinstance(response, dict):
            raise AIServiceError("Volcengine API 返回结构无效", kind="provider_invalid_response", retryable=True)
        return response

    @staticmethod
    def _response_text(response: dict[str, Any]) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIServiceError("模型响应缺少 choices[0].message.content", kind="provider_invalid_response", retryable=True) from exc
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
        raise AIServiceError("模型响应 content 类型无效", kind="provider_invalid_response", retryable=True)

    @staticmethod
    def _json_object(text: str) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise AIServiceError("模型未返回有效 JSON", kind="provider_invalid_response", retryable=True)
            try:
                result = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise AIServiceError("模型未返回有效 JSON", kind="provider_invalid_response", retryable=True) from exc
        if not isinstance(result, dict):
            raise AIServiceError("模型 JSON 根节点必须为对象", kind="provider_invalid_response", retryable=True)
        return result

    def _chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.4,
        json_object: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        if not model.strip():
            raise AIServiceError("对应的 DOUBAO_*_MODEL 未配置", kind="provider_configuration_error", retryable=False)
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_object:
            payload["response_format"] = {"type": "json_object"}
        return self._response_text(self._post_json(settings.doubao_chat_endpoint, payload))

    @staticmethod
    def _audio_content(audio: dict[str, Any] | None, audio_path: str) -> dict[str, Any]:
        source = audio or {}
        audio_format = source.get("format") or Path(audio_path).suffix.lstrip(".") or "wav"
        encoded = source.get("base64")
        if isinstance(encoded, str) and encoded.startswith("data:") and "," in encoded:
            encoded = encoded.partition(",")[2]
        if not encoded:
            source_url = source.get("url") or audio_path
            if source_url.startswith(("https://", "http://")):
                return {"type": "input_audio", "input_audio": {"url": source_url, "format": audio_format}}
            path = Path(source_url) if source_url else None
            if path and path.is_file():
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            else:
                raise AIServiceError("ASR 需要音频 base64、可访问 URL 或本地音频文件", kind="invalid_audio_input", retryable=False)
        try:
            base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise AIServiceError("音频 base64 格式无效", kind="invalid_audio_input", retryable=False) from exc
        return {"type": "input_audio", "input_audio": {"data": encoded, "format": audio_format}}

    def asr(self, audio: dict[str, Any] | None = None, *, audio_path: str = "") -> dict[str, Any]:
        content = self._audio_content(audio, audio_path)
        text = self._chat_completion(
            build_audio_analysis_messages(content),
            model=settings.doubao_asr_model,
            temperature=0,
            json_object=True,
        )
        result = self._json_object(text)
        transcription = result.get("transcription", result.get("text", ""))
        if not isinstance(transcription, str):
            raise AIServiceError("ASR 模型未返回文本转写", kind="provider_invalid_response", retryable=True)
        return {"text": transcription.strip(), **AI_VERSIONS}

    def analyze_emotion(self, text: str, *, recent_dialogue: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        result_text = self._chat_completion(
            build_text_emotion_messages(text, recent_dialogue),
            model=settings.doubao_emotion_model,
            temperature=0,
            json_object=True,
        )
        return {**self._json_object(result_text), **AI_VERSIONS}

    def chat(
        self,
        text: str,
        emotion: dict[str, Any] | None = None,
        *,
        persona: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        session_type: str | None = None,
        user_memories: list[dict[str, Any]] | None = None,
        followup_memories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        messages = build_dialogue_messages(
            text,
            emotion,
            persona=persona,
            context=context,
            session_type=session_type,
            user_memories=user_memories,
            followup_memories=followup_memories,
        )
        result = self._chat_completion(messages, model=settings.doubao_dialogue_model, temperature=0.7)
        if not result:
            raise AIServiceError("对话模型返回空文本", kind="provider_invalid_response", retryable=True)
        return {"text": result, **AI_VERSIONS}

    def tts(
        self,
        text: str,
        *,
        request_id: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        if not settings.doubao_tts_model.strip():
            raise AIServiceError("DOUBAO_TTS_MODEL 未配置", kind="provider_configuration_error", retryable=False)
        payload: dict[str, Any] = {
            "model": settings.doubao_tts_model,
            "input": text,
            "instructions": instructions or settings.doubao_tts_voice_prompt,
            "response_format": settings.doubao_tts_response_format,
        }
        selected_voice = voice or settings.doubao_tts_voice
        if selected_voice:
            payload["voice"] = selected_voice
        raw, content_type = self._post(settings.doubao_tts_endpoint, payload, accept="audio/*, application/json")
        audio_url = None
        if "json" in content_type:
            try:
                response = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AIServiceError("TTS API 返回的 JSON 格式无效", kind="provider_invalid_response", retryable=True) from exc
            encoded = response.get("audio_base64") or response.get("audio") or response.get("b64_json")
            audio_url = response.get("audio_url") or response.get("url")
            if isinstance(encoded, str) and encoded.startswith("data:") and "," in encoded:
                encoded = encoded.partition(",")[2]
            if encoded is not None and not isinstance(encoded, str):
                raise AIServiceError("TTS API 音频内容类型无效", kind="provider_invalid_response", retryable=True)
            if audio_url is not None and not isinstance(audio_url, str):
                raise AIServiceError("TTS API 音频 URL 类型无效", kind="provider_invalid_response", retryable=True)
            if not encoded and not audio_url:
                raise AIServiceError("TTS API 未返回音频内容或 URL", kind="provider_invalid_response", retryable=True)
            audio_base64 = encoded
        else:
            audio_base64 = base64.b64encode(raw).decode("ascii")
        return {
            "audio_id": request_id or str(uuid4()),
            "audio_url": audio_url,
            "audio_base64": audio_base64,
            "audio_format": settings.doubao_tts_response_format,
            **AI_VERSIONS,
        }


def get_doubao_client() -> DoubaoClient:
    return MockDoubaoClient() if settings.doubao_mode == "mock" else RealDoubaoClient()


def call_with_retry(operation, *, operation_name: str):
    started = time.monotonic()
    max_attempts = 1 + max(0, settings.ai_retry_max)
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        if time.monotonic() - started >= settings.ai_timeout_ms / 1000:
            raise AITimeoutError(f"{operation_name} 超过后端总超时")
        try:
            return operation()
        except AITimeoutError:
            raise
        except AIServiceError as exc:
            if not exc.retryable:
                raise
            last_error = exc
        except Exception as exc:
            last_error = exc
        if attempt + 1 >= max_attempts:
            break
        delays = settings.ai_retry_backoff_ms
        delay_ms = delays[min(attempt, len(delays) - 1)] if delays else 0
        if delay_ms:
            time.sleep(min(delay_ms / 1000, max(0, settings.ai_timeout_ms / 1000 - (time.monotonic() - started))))
    if isinstance(last_error, AIServiceError):
        raise AIServiceError(
            f"{operation_name} 失败: {last_error}",
            kind=last_error.kind,
            retryable=last_error.retryable,
        ) from last_error
    raise AIServiceError(f"{operation_name} 失败: {last_error}") from last_error
