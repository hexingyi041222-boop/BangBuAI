from __future__ import annotations

from typing import Any, Protocol


class BackendToolError(RuntimeError):
    """Base error for a business-tool backend call."""

    def __init__(self, message: str, *, code: str = "BACKEND_ERROR", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class BackendToolNotConfigured(BackendToolError):
    """Raised until the external business API adapter is connected."""

    def __init__(self, message: str):
        super().__init__(message, code="BACKEND_UNCONFIGURED", retryable=False)


class BackendToolClient(Protocol):
    def set_pomodoro(self, user_id: str, *, focus_minutes: int | None = None, break_minutes: int | None = None) -> dict[str, Any]: ...
    def start_pomodoro(self, user_id: str) -> dict[str, Any]: ...
    def stop_pomodoro(self, user_id: str) -> dict[str, Any]: ...
    def update_pet_settings(self, user_id: str, settings: dict[str, Any]) -> dict[str, Any]: ...
    def query_orders(self, user_id: str, filters: dict[str, Any]) -> dict[str, Any]: ...
    def publish_post(self, user_id: str, post: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]: ...
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
        """Ask the backend to dispatch audio; success means accepted, not device-acked."""


class UnconfiguredBackendToolClient:
    """Explicit integration seam; business endpoints are intentionally not guessed."""

    def _not_configured(self, operation: str) -> None:
        raise BackendToolNotConfigured(f"业务后端接口尚未接入：{operation}")

    def set_pomodoro(self, user_id: str, *, focus_minutes: int | None = None, break_minutes: int | None = None) -> dict[str, Any]:
        self._not_configured("pomodoro.set")

    def start_pomodoro(self, user_id: str) -> dict[str, Any]:
        self._not_configured("pomodoro.start")

    def stop_pomodoro(self, user_id: str) -> dict[str, Any]:
        self._not_configured("pomodoro.stop")

    def update_pet_settings(self, user_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        self._not_configured("pet.update")

    def query_orders(self, user_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        self._not_configured("orders.query")

    def publish_post(self, user_id: str, post: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        self._not_configured("posts.publish")

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
        self._not_configured("hardware.tts.dispatch")


_configured_client: BackendToolClient | None = None


def configure_backend_tool_client(client: BackendToolClient | None) -> None:
    """Install the backend adapter during application startup, before serving requests."""
    global _configured_client
    _configured_client = client


def get_backend_tool_client() -> BackendToolClient:
    return _configured_client if _configured_client is not None else UnconfiguredBackendToolClient()
