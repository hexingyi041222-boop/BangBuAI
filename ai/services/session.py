from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from time import time
from typing import Any, Callable

from app.core.config import settings
from app.core.contracts import SessionState


def now_ms() -> int:
    return int(time() * 1000)


@dataclass
class Session:
    session_id: str
    user_id: str | None
    device_id: str | None
    started_at: int
    last_active_at: int
    state: SessionState = "active"
    failure_count: int = 0
    ended_reason: str | None = None
    silence_at: int | None = None
    followup_checked: bool = False
    followup_memories: list[dict[str, Any]] = field(default_factory=list)
    followup_decision: dict[str, Any] = field(default_factory=dict)


class SessionStore:
    def __init__(self) -> None:
        self._items: dict[str, Session] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str, *, user_id: str | None = None, device_id: str | None = None) -> Session:
        with self._lock:
            item = self._items.get(session_id)
            if item is None:
                current = now_ms()
                item = Session(session_id, user_id, device_id, current, current)
                self._items[session_id] = item
            return item

    def touch(self, session_id: str) -> Session:
        with self._lock:
            item = self._items[session_id]
            if item.state == "active":
                item.last_active_at = now_ms()
            return item

    def begin(self, session_id: str, *, user_id: str | None = None, device_id: str | None = None) -> Session:
        return self.get_or_create(session_id, user_id=user_id, device_id=device_id)

    def get_or_initialize_followup_context(
        self,
        session_id: str,
        initializer: Callable[[], tuple[list[dict[str, Any]], dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
        """Load opening follow-up context once, then reuse it for this session."""
        with self._lock:
            item = self._items[session_id]
            initialized = False
            if not item.followup_checked:
                memories, decision = initializer()
                item.followup_memories = deepcopy(memories)
                item.followup_decision = deepcopy(decision)
                item.followup_checked = True
                initialized = True
            return deepcopy(item.followup_memories), deepcopy(item.followup_decision), initialized

    def mark_followup_handled(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(session_id)
            if not item:
                return None
            if item.followup_decision.get("should_followup"):
                item.followup_decision["followup_status"] = "followed"
            return deepcopy(item.followup_decision)

    def end(self, session_id: str, reason: str = "user_end") -> Session | None:
        with self._lock:
            item = self._items.get(session_id)
            if item:
                item.state = "ended"
                item.ended_reason = reason
            return item

    def mark_silent(self, session_id: str, reason: str = "failure_threshold") -> Session | None:
        with self._lock:
            item = self._items.get(session_id)
            if item and item.state == "active":
                item.state = "silent"
                item.silence_at = now_ms()
            return item

    def increment_failure(self, session_id: str) -> Session | None:
        with self._lock:
            item = self._items.get(session_id)
            if item:
                item.failure_count += 1
                if item.failure_count >= settings.failure_silence_threshold:
                    item.state = "silent"
                    item.silence_at = now_ms()
            return item

    def reset_failure(self, session_id: str) -> Session | None:
        with self._lock:
            item = self._items.get(session_id)
            if item:
                item.failure_count = 0
            return item

    def status(self, session_id: str) -> Session | None:
        with self._lock:
            item = self._items.get(session_id)
            if item and item.state == "active" and now_ms() - item.last_active_at >= settings.session_max_idle_ms:
                item.state = "ended"
                item.ended_reason = "no_input_timeout"
            return item


session_store = SessionStore()
