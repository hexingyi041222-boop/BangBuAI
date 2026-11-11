"""Pure presentation rules for saved analyses; this module never calls an AI API."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any


REPORT_TIMEZONE = timezone(timedelta(hours=8))
# 对外只保留五类用户/陪伴情绪；旧标签通过 normalize_emotion_label 兼容归并。
LABELS_CN = {"happy": "开心", "calm": "平静", "tired": "疲惫", "anxious": "焦虑", "down": "低落"}
EMOTION_LABEL_ALIASES = {
    "happy": "happy",
    "开心": "happy",
    "calm": "calm",
    "平静": "calm",
    "neutral": "calm",
    "中性": "calm",
    "bored": "calm",
    "无聊": "calm",
    "tired": "tired",
    "疲惫": "tired",
    "anxious": "anxious",
    "焦虑": "anxious",
    "down": "down",
    "低落": "down",
    "sad": "down",
    "angry": "down",
    "生气": "down",
}
PERIODS = (("early_morning", "早上", 6, 9), ("morning", "上午", 9, 12), ("afternoon", "下午", 12, 18), ("evening", "晚上", 18, 24), ("late_night", "深夜", 0, 6))
TOPIC_KEYWORDS = {
    "工作进展": ("工作", "项目", "进度", "开会"),
    "午餐计划": ("午饭", "午餐", "吃饭"),
    "周末期待": ("周末", "放假"),
    "朋友聊天": ("朋友", "同学"),
    "休息睡眠": ("休息", "睡觉", "困"),
}


def bounded_number(value: Any, *, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number)) if isfinite(number) else default


def normalize_emotion_label(value: Any, *, default: str = "calm") -> str:
    """将模型、历史数据或中文标签归并为五类标准标签。"""

    raw = str(value or "").strip().lower()
    return EMOTION_LABEL_ALIASES.get(raw, default)


def normalize_content_tags(value: Any, *, limit: int = 3) -> list[str]:
    """保留四字事件标签，去重并限制数量。"""

    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        tag = item.strip()
        if len(tag) == 4 and tag not in tags:
            tags.append(tag)
        if len(tags) >= limit:
            break
    return tags


def user_emotion_score(label: str, intensity: float) -> int:
    """A display index, not a psychometric measurement or the pet's score."""
    direction = 1 if normalize_emotion_label(label) == "happy" else 0 if normalize_emotion_label(label) == "calm" else -1
    return round(50 + direction * 50 * intensity)


def rule_content_metadata(text: str) -> dict[str, Any]:
    tags = [tag for tag, keywords in TOPIC_KEYWORDS.items() if any(keyword in text for keyword in keywords)][:5]
    return {"content_tags": tags, "content_summary": text.strip()[:80]}


def build_daily_summary(*, user_id: str, report_date: str, events: list[dict]) -> dict:
    distribution = dict(Counter(event["label"] for event in events))
    result = {
        "user_id": user_id, "report_date": report_date,
        "status": "available" if events else "insufficient_data",
        "coverage_count": len(events), "interaction_count": len(events),
        "summary_text": None, "daily_message": None, "daily_message_source": None,
        "emotions": events, "label_distribution": distribution,
        "emotion_curve": [], "periods": [], "abnormal_events": [],
        "bangbu_emotion_curve": [], "score_rule": "label_intensity_v1",
    }
    for event in events:
        result["emotion_curve"].append({key: event.get(key) for key in ("event_id", "timestamp", "label", "intensity", "emotion_score", "confidence")})
        if event.get("need_followup"):
            result["abnormal_events"].append(event)
        if event.get("bangbu_emotion"):
            result["bangbu_emotion_curve"].append({"timestamp": event["timestamp"], **event["bangbu_emotion"]})
    for key, title, start, end in PERIODS:
        items = [event for event in events if start <= datetime.fromtimestamp(event["timestamp"] / 1000, REPORT_TIMEZONE).hour < end]
        if items:
            scores = [event["emotion_score"] for event in items if event.get("emotion_score") is not None]
            result["periods"].append({"period": key, "label_cn": title, "count": len(items), "emotion_score": round(sum(scores) / len(scores)) if scores else None, "events": items})
    if events:
        dominant = max(distribution, key=distribution.get)
        title = LABELS_CN.get(dominant, dominant)
        result["summary_text"] = f"当天有 {len(events)} 次情绪分析，主要为{title}；其中 {len(result['abnormal_events'])} 次需要关注。分析仅供参考。"
        result["daily_message"] = f"今天我们有 {len(events)} 次交流记录。谢谢你愿意和我分享，接下来也按自己的节奏安排生活吧。"
        result["daily_message_source"] = "template"
    return result
