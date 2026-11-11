from __future__ import annotations

from typing import Any, NoReturn
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import settings
from app.services.backend_tools import BackendToolError


_PET_FIELDS = {"name", "gender", "personality", "mbti", "voice", "speaking_style", "relationship", "custom_keywords"}
_POST_FIELDS = {"content", "title", "topic", "visibility"}
_ORDER_FIELDS = {"order_id", "status", "limit", "offset"}
_ORDER_STATUSES = {"pending_payment", "shipping", "completed"}
_TTS_FORMATS = {"mp3", "wav", "opus", "pcm"}


class BackendToolHTTPClient:
    """HTTP adapter for the business backend's internal v1 endpoints."""

    def __init__(
        self,
        base_url: str,
        service_token: str,
        *,
        connect_timeout: float = 2.0,
        read_timeout: float = 5.0,
        tts_read_timeout: float = 10.0,
        http_client: httpx.Client | None = None,
    ):
        normalized_base_url = base_url.strip()
        parsed = urlsplit(normalized_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("BACKEND_API_BASE_URL must be an absolute HTTP(S) URL")
        if not service_token.strip():
            raise ValueError("BACKEND_SERVICE_TOKEN must not be empty")

        self.base_url = normalized_base_url.rstrip("/")
        self._token = service_token.strip()
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._tts_read_timeout = tts_read_timeout
        self._client = http_client or httpx.Client()
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        tts_timeout: bool = False,
    ) -> dict[str, Any]:
        read_timeout = self._tts_read_timeout if tts_timeout else self._read_timeout
        headers = {"Authorization": f"Bearer {self._token}"}
        if idempotency_key is not None:
            if not idempotency_key.strip():
                raise BackendToolError("幂等键不能为空", code="INVALID_IDEMPOTENCY_KEY")
            headers["Idempotency-Key"] = idempotency_key
        timeout = httpx.Timeout(
            connect=self._connect_timeout,
            read=read_timeout,
            write=read_timeout,
            pool=self._connect_timeout,
        )

        try:
            response = self._client.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=body,
                headers=headers,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise BackendToolError("业务后端请求超时", code="BACKEND_TIMEOUT", retryable=True) from exc
        except httpx.RequestError as exc:
            raise BackendToolError("业务后端暂不可用", code="BACKEND_UNAVAILABLE", retryable=True) from exc

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if not response.is_success:
            if isinstance(payload, dict) and payload.get("ok") is False:
                self._raise_envelope_error(payload, response.status_code)
            retryable = response.status_code in {408, 425, 429} or response.status_code >= 500
            raise BackendToolError(
                "业务后端返回 HTTP 错误",
                code=f"BACKEND_HTTP_{response.status_code}",
                retryable=retryable,
            )
        if not isinstance(payload, dict):
            raise BackendToolError("业务后端响应不是有效 JSON 对象", code="BACKEND_INVALID_RESPONSE")
        if payload.get("ok") is False:
            self._raise_envelope_error(payload, response.status_code)
        if payload.get("ok") is not True or not isinstance(payload.get("data"), dict):
            raise BackendToolError("业务后端响应不符合统一响应格式", code="BACKEND_INVALID_RESPONSE")
        return payload["data"]

    @staticmethod
    def _raise_envelope_error(payload: dict[str, Any], status_code: int) -> NoReturn:
        error = payload.get("error")
        if not isinstance(error, dict):
            raise BackendToolError(
                "业务后端返回业务错误",
                code=f"BACKEND_HTTP_{status_code}" if status_code >= 400 else "BACKEND_ERROR",
                retryable=status_code in {408, 425, 429} or status_code >= 500,
            )
        code = str(error.get("code") or "BACKEND_ERROR")
        retryable = error.get("retryable")
        if not isinstance(retryable, bool):
            retryable = status_code in {408, 425, 429} or status_code >= 500
        # Do not include arbitrary backend messages in exceptions, which may be logged upstream.
        raise BackendToolError("业务后端拒绝了请求", code=code, retryable=retryable)

    @staticmethod
    def _validate_optional_int(value: int | None, field: str, minimum: int, maximum: int) -> None:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum
        ):
            raise BackendToolError(f"{field} 超出允许范围", code="INVALID_ARGUMENT")

    def set_pomodoro(
        self,
        user_id: str,
        *,
        focus_minutes: int | None = None,
        break_minutes: int | None = None,
    ) -> dict[str, Any]:
        self._validate_optional_int(focus_minutes, "focus_minutes", 1, 180)
        self._validate_optional_int(break_minutes, "break_minutes", 1, 60)
        if focus_minutes is None and break_minutes is None:
            raise BackendToolError("至少需要设置一项番茄钟时长", code="INVALID_ARGUMENT")
        body: dict[str, Any] = {"user_id": user_id}
        if focus_minutes is not None:
            body["focus_minutes"] = focus_minutes
        if break_minutes is not None:
            body["break_minutes"] = break_minutes
        return self._request("PUT", "/internal/v1/pomodoro/settings", body=body)

    def start_pomodoro(self, user_id: str) -> dict[str, Any]:
        return self._request("POST", "/internal/v1/pomodoro/start", body={"user_id": user_id})

    def stop_pomodoro(self, user_id: str) -> dict[str, Any]:
        return self._request("POST", "/internal/v1/pomodoro/stop", body={"user_id": user_id})

    def update_pet_settings(self, user_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        updates = {key: value for key, value in settings.items() if key in _PET_FIELDS}
        if not updates:
            raise BackendToolError("桌宠设置没有可更新字段", code="INVALID_ARGUMENT")
        for key, value in updates.items():
            if key == "custom_keywords":
                valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
            else:
                valid = isinstance(value, str)
            if not valid:
                raise BackendToolError(f"{key} 字段类型无效", code="INVALID_ARGUMENT")
        user_path = quote(user_id, safe="")
        return self._request("PATCH", f"/internal/v1/users/{user_path}/pet-settings", body=updates)

    def query_orders(self, user_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        query: dict[str, Any] = {"user_id": user_id}
        for key, value in filters.items():
            if key not in _ORDER_FIELDS or value is None:
                continue
            if key == "status" and (not isinstance(value, str) or value not in _ORDER_STATUSES):
                raise BackendToolError("订单状态无效", code="INVALID_ARGUMENT")
            if key in {"limit", "offset"}:
                minimum = 1 if key == "limit" else 0
                if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                    raise BackendToolError(f"{key} 参数无效", code="INVALID_ARGUMENT")
            query[key] = value
        return self._request("GET", "/internal/v1/orders", params=query)

    def publish_post(self, user_id: str, post: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        if not _POST_FIELDS.issubset(post):
            raise BackendToolError("帖子字段不完整", code="INVALID_ARGUMENT")
        if (
            not isinstance(post["visibility"], str)
            or post["visibility"] not in {"public", "friends", "private"}
        ):
            raise BackendToolError("帖子可见范围无效", code="INVALID_ARGUMENT")
        return self._request(
            "POST",
            "/internal/v1/posts",
            body={"user_id": user_id, "post": {key: post[key] for key in _POST_FIELDS}},
            idempotency_key=idempotency_key,
        )

    def dispatch_tts_to_device(
        self,
        *,
        user_id: str,
        device_id: str,
        audio_id: str,
        audio_url: str | None,
        audio_base64: str | None,
        audio_format: str | None,
        text: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not isinstance(user_id, str) or not user_id.strip():
            raise BackendToolError("TTS 派发必须提供 user_id", code="INVALID_ARGUMENT")
        if not device_id.strip():
            raise BackendToolError("TTS 派发必须提供 device_id", code="INVALID_ARGUMENT")
        if not audio_url and not audio_base64:
            raise BackendToolError("audio_url 与 audio_base64 至少提供一个", code="INVALID_ARGUMENT")
        if idempotency_key != audio_id:
            raise BackendToolError("TTS 幂等键必须与 audio_id 一致", code="INVALID_IDEMPOTENCY_KEY")
        if audio_format is not None and (
            not isinstance(audio_format, str) or audio_format not in _TTS_FORMATS
        ):
            raise BackendToolError("音频格式无效", code="INVALID_ARGUMENT")
        body = {
            "user_id": user_id,
            "device_id": device_id,
            "audio_id": audio_id,
            "audio_url": audio_url,
            # The contract prefers a downloadable URL whenever both encodings exist.
            "audio_base64": None if audio_url else audio_base64,
            "text": text,
            "idempotency_key": idempotency_key,
        }
        # Omit optional fields set to None so the backend can apply schema defaults.
        if audio_format is not None:
            body["audio_format"] = audio_format
        result = self._request(
            "POST",
            "/internal/v1/tts/dispatch",
            body=body,
            idempotency_key=idempotency_key,
            tts_timeout=True,
        )
        if result.get("state") != "accepted":
            raise BackendToolError(
                "业务后端未确认接受 TTS 派发",
                code="TTS_DISPATCH_NOT_ACCEPTED",
                retryable=False,
            )
        return result


def create_backend_tool_client_from_settings() -> BackendToolHTTPClient | None:
    base_url = settings.backend_api_base_url.strip()
    service_token = settings.backend_service_token.strip()
    if not base_url and not service_token:
        return None
    if not base_url or not service_token:
        raise RuntimeError("BACKEND_API_BASE_URL 与 BACKEND_SERVICE_TOKEN 必须同时配置")
    return BackendToolHTTPClient(
        base_url,
        service_token,
        connect_timeout=settings.backend_connect_timeout_seconds,
        read_timeout=settings.backend_read_timeout_seconds,
        tts_read_timeout=settings.backend_tts_read_timeout_seconds,
    )
