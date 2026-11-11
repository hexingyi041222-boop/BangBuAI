from __future__ import annotations

import json
import re
from typing import Any

from app.storage.repository import repository


def _clean(value: str) -> str:
    return re.sub(r"[，。！？；,.!?;]+$", "", value.strip())


def extract_memory_candidates(text: str) -> list[dict[str, Any]]:
    """从用户明确表达中提取低风险、可解释的长期记忆候选。"""
    text = text.strip()
    if not text:
        return []
    patterns = [
        ("basic_profile", "name", r"(?:我叫|我的名字是|你可以叫我)([^，。！？；,!?;]{1,20})", 0.95),
        ("interest", "interest", r"(?:我喜欢|我爱|我最喜欢|我对)([^，。！？；,!?;]{1,40})(?:感兴趣)?", 0.82),
        ("avoidance", "avoidance", r"(?:我不喜欢|我讨厌|我不爱)([^，。！？；,!?;]{1,40})", 0.88),
        ("habit", "habit", r"(?:我通常|我一般|我习惯|我每天|我平时|平时通常)([^，。！？；,!?;]{1,50})", 0.75),
        ("preference", "conversation_style", r"(?:我希望你|你可以)([^，。！？；,!?;]{1,50})", 0.8),
    ]
    candidates: list[dict[str, Any]] = []
    for memory_type, key, pattern, confidence in patterns:
        match = re.search(pattern, text)
        if match:
            value = _clean(match.group(1))
            if value:
                candidates.append({"memory_type": memory_type, "memory_key": key if key != "interest" else value[:30], "memory_value": value, "confidence": confidence, "source_text": text})
    return candidates


def recall_user_memories(user_id: str | None, text: str, *, limit: int = 8) -> list[dict[str, Any]]:
    return repository.list_user_memories(user_id, query=text, limit=limit) if user_id else []


def learn_user_memories(user_id: str | None, text: str) -> list[dict[str, Any]]:
    if not user_id:
        return []
    return [repository.upsert_user_memory(user_id=user_id, **candidate) for candidate in extract_memory_candidates(text)]


def upsert_user_memories(user_id: str, settings: dict[str, Any], source_text: str) -> list[dict[str, Any]]:
    """Persist explicit pet-persona preferences as durable, recallable memories."""
    updates = []
    for key, value in settings.items():
        serialized = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value)
        updates.append(
            repository.upsert_user_memory(
                user_id=user_id,
                memory_type="persona_preference",
                memory_key=key,
                memory_value=serialized,
                confidence=0.98,
                source_text=source_text,
            )
        )
    return updates
