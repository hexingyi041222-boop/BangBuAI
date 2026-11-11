from __future__ import annotations

from threading import Lock
from time import monotonic
from typing import Protocol

from app.core.config import settings


class FailureCounter(Protocol):
    def increment(self, session_id: str) -> int: ...
    def get(self, session_id: str) -> int: ...
    def clear(self, session_id: str) -> None: ...
    def increment_failure(self, session_id: str) -> int: ...


class MemoryFailureCounter:
    def __init__(self) -> None:
        self._data: dict[str, tuple[int, float]] = {}
        self._lock = Lock()

    def _read(self, session_id: str) -> int:
        item = self._data.get(f"session:{session_id}:failure_count")
        if not item or item[1] <= monotonic():
            return 0
        return item[0]

    def increment(self, session_id: str) -> int:
        with self._lock:
            key = f"session:{session_id}:failure_count"
            count = self._read(session_id) + 1
            self._data[key] = (count, monotonic() + settings.session_ttl_ms / 1000 + 300)
            return count

    def get(self, session_id: str) -> int:
        with self._lock:
            return self._read(session_id)

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(f"session:{session_id}:failure_count", None)

    def increment_failure(self, session_id: str) -> int:
        return self.increment(session_id)


class RedisFailureCounter:
    def increment(self, session_id: str) -> int:
        raise NotImplementedError("TODO(confirm): Redis 连接配置 | owner=运维/技术")

    def get(self, session_id: str) -> int:
        raise NotImplementedError

    def clear(self, session_id: str) -> None:
        raise NotImplementedError


failure_counter: FailureCounter = MemoryFailureCounter()
