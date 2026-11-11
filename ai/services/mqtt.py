from dataclasses import dataclass, field
from threading import Lock
from time import time

@dataclass
class MQTTMessage:
    topic: str
    payload: dict
    qos: int = 1
    message_id: str | None = None
    created_at: float = field(default_factory=time)

class MockMQTTClient:
    def __init__(self): self._messages: list[MQTTMessage] = []; self._seen: set[str] = set(); self._lock = Lock()
    def publish(self, topic: str, payload: dict, *, qos: int = 1, message_id: str | None = None) -> MQTTMessage:
        with self._lock:
            if message_id and message_id in self._seen:
                return next(m for m in self._messages if m.message_id == message_id)
            message = MQTTMessage(topic, payload, qos, message_id)
            self._messages.append(message)
            if message_id: self._seen.add(message_id)
            return message
    def subscribe(self, topic: str) -> list[MQTTMessage]:
        with self._lock: return [m for m in self._messages if m.topic == topic]
    def offline_messages(self) -> list[MQTTMessage]:
        with self._lock: return list(self._messages)

mqtt_client = MockMQTTClient()
