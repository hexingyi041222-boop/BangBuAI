from __future__ import annotations

import re
from typing import Any


_PUNCTUATION = "，。！？；,.!?;：: \t\n"


def _clean_value(value: str) -> str:
    return value.strip(_PUNCTUATION + "\"'“”‘’")


def _first_value(patterns: tuple[str, ...], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = _clean_value(match.group(1))
            if value:
                return value
    return None


def parse_tool_intent(text: str) -> dict[str, Any] | None:
    """Parse the MVP's explicit voice-command vocabulary into whitelisted tools."""
    normalized = text.strip()
    if not normalized:
        return None

    if re.search(r"(?:帮我|替我|给我).{0,4}(?:买|下单)|代购|购物|我要购买", normalized):
        return {"name": "shopping.blocked", "arguments": {}}

    if re.search(r"(?:查|查询|看看|查看|跟踪).{0,8}(?:订单|物流|快递)|(?:我的订单|订单状态|物流到哪|快递到哪)", normalized):
        order_id = _first_value((r"(?:订单号|订单编号)\s*(?:是|为|叫|[:：])?\s*([A-Za-z0-9_-]{3,40})",), normalized)
        status = None
        if re.search(r"(?:待支付|未付款)", normalized):
            status = "pending_payment"
        elif re.search(r"(?:已发货|运输中|物流)", normalized):
            status = "shipping"
        elif re.search(r"(?:已完成|已签收)", normalized):
            status = "completed"
        filters = {key: value for key, value in {"order_id": order_id, "status": status}.items() if value}
        return {"name": "orders.query", "arguments": filters}

    if "番茄钟" in normalized or "番茄计时" in normalized:
        if re.search(r"(?:关闭|停止|结束|关掉|停掉|中断)", normalized):
            return {"name": "pomodoro.stop", "arguments": {}}
        if re.search(r"(?:开启|打开|开始|启动)", normalized):
            return {"name": "pomodoro.start", "arguments": {}}
        if re.search(r"(?:设置|调整|改成|改为|设成|设为|分钟)", normalized):
            focus = _first_value((r"(?:专注|工作|番茄钟?)(?:时间|时长)?\s*(?:设置为|调整为|改成|改为|设成|设为|是|为)?\s*(\d{1,3})\s*(?:分钟|分)",), normalized)
            if not focus and not re.search(r"休息", normalized):
                focus = _first_value((r"(\d{1,3})\s*(?:分钟|分)",), normalized)
            rest = _first_value((r"(?:休息|短休息)(?:时间|时长)?\s*(?:设置为|调整为|改成|改为|设成|设为|是|为)?\s*(\d{1,3})\s*(?:分钟|分)",), normalized)
            args = {}
            if focus:
                value = int(focus)
                if 1 <= value <= 180:
                    args["focus_minutes"] = value
            if rest:
                value = int(rest)
                if 1 <= value <= 60:
                    args["break_minutes"] = value
            return {"name": "pomodoro.set", "arguments": args}

    pet_settings = _parse_pet_settings(normalized)
    if pet_settings is not None:
        return {"name": "pet.update", "arguments": {"settings": pet_settings}}

    if re.search(r"(?:发帖|发帖子|发布帖子|发布一条帖子|发一条帖子|发个帖子|发布动态)", normalized):
        return {"name": "posts.draft", "arguments": _parse_post_fields(normalized)}

    return None


def _parse_pet_settings(text: str) -> dict[str, Any] | None:
    settings: dict[str, Any] = {}
    patterns = {
        "name": (
            r"(?:桌宠|邦布|你)?(?:以后)?(?:的)?(?:名字|称呼)\s*(?:改成|设置为|设为|叫|是|为)?\s*([^，。！？；,.!?;]+)",
            r"(?:桌宠|邦布|你)(?:以后)?叫\s*([^，。！？；,.!?;]+)",
        ),
        "personality": (r"(?:性格|个性|人格)\s*(?:改成|设置为|设为|是|为)?\s*([^，。！？；,.!?;]+)",),
        "speaking_style": (
            r"(?:说话风格|说话方式|语气|风格)\s*(?:改成|设置为|设为|是|为|更)?\s*([^，。！？；,.!?;]+)",
            r"说话更\s*([^，。！？；,.!?;]+)",
        ),
        "relationship": (r"(?:关系称呼|关系|把我当成)\s*(?:改成|设置为|设为|是|为)?\s*([^，。！？；,.!?;]+)",),
        "gender": (r"性别\s*(?:改成|设置为|设为|是|为)?\s*([^，。！？；,.!?;]+)",),
        "mbti": (r"MBTI\s*(?:改成|设置为|设为|是|为)?\s*((?:I|E)(?:N|S)(?:T|F)(?:J|P))\b",),
        "voice": (r"(?:音色|声音)\s*(?:改成|设置为|设为|是|为)\s*([A-Za-z0-9_-]+)",),
        "custom_keywords": (r"(?:关键词|口头禅)\s*(?:改成|设置为|设为|是|为)?\s*([^，。！？；,.!?;]+)",),
    }
    for key, key_patterns in patterns.items():
        value = _first_value(key_patterns, text)
        if value:
            settings[key] = [part.strip() for part in re.split(r"[、,，]", value) if part.strip()] if key == "custom_keywords" else value.upper() if key == "mbti" else value

    explicit_personalization = "桌宠" in text and re.search(r"(?:设置|修改|调整|改成|个性化)", text)
    direct_pet_preference = any(word in text for word in ("你以后", "你说话", "邦布以后", "桌宠以后"))
    if settings or explicit_personalization or direct_pet_preference:
        return settings
    return None


def _parse_post_fields(text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    separator = r"(?:改成|改为|设置为|设为|是|叫|为|[:：])?"
    title = _first_value((rf"(?:标题|题目)\s*{separator}\s*(.+?)(?=(?:话题|标签|可见|范围|内容)\s*(?:改成|改为|设置为|设为|是|为|[:：])?|$)",), text)
    topic = _first_value((rf"(?:话题|标签)\s*{separator}\s*(.+?)(?=(?:标题|题目|可见|范围|内容)\s*(?:改成|改为|设置为|设为|是|为|[:：])?|$)",), text)
    content = _first_value((rf"内容\s*{separator}\s*(.+?)(?=(?:标题|题目|话题|标签|可见|范围)\s*(?:改成|改为|设置为|设为|是|为|[:：])?|$)",), text)
    if not content:
        match = re.search(r"(?:发帖|发帖子|发布帖子|发布一条帖子|发一条帖子|发个帖子|发布动态)(.*)$", text)
        if match:
            remainder = _clean_value(match.group(1))
            remainder = re.sub(r"^(?:我想说|说一下|内容(?:是|为)?|正文(?:是|为)?)\s*", "", remainder)
            remainder = re.sub(r"(?:标题|题目|话题|标签|可见范围|可见)\s*(?:是|为|[:：]).*$", "", remainder)
            content = _clean_value(remainder)
    if title:
        fields["title"] = title
    if topic:
        fields["topic"] = None if topic in {"无", "不加", "不需要", "没有"} else topic.lstrip("#")
    if content:
        fields["content"] = content
    visibility = _parse_visibility(text)
    if visibility:
        fields["visibility"] = visibility
    return fields


def _parse_visibility(text: str) -> str | None:
    if re.search(r"(?:仅自己|只有自己|私密|不公开)", text):
        return "private"
    if re.search(r"(?:好友可见|仅好友|朋友可见)", text):
        return "friends"
    if re.search(r"(?:公开|所有人可见|所有人都能看)", text):
        return "public"
    return None


def extract_post_field_updates(text: str) -> dict[str, Any]:
    return _parse_post_fields(text)


def parse_post_field_answer(field: str, text: str) -> Any | None:
    value = text.strip()
    if field == "visibility":
        return _parse_visibility(value)
    if field == "topic" and re.search(r"(?:无|不加|不需要|没有)(?:话题|标签)?", value):
        return None
    if field == "content":
        fields = _parse_post_fields(value)
        if fields.get("content"):
            return fields["content"]
    if field == "title":
        match = re.search(r"^(?:标题|題目)\s*(?:是|叫|为|[:：])?\s*(.+)$", value)
        if match:
            return _clean_value(match.group(1))
    if field == "topic":
        match = re.search(r"^(?:话题|标签)\s*(?:是|叫|为|[:：])?\s*(.+)$", value)
        if match:
            return _clean_value(match.group(1)).lstrip("#")
        if value.startswith("#"):
            return value.lstrip("#").split()[0]
    if field == "content":
        return _clean_value(value)
    if field == "title" and not re.search(r"(?:取消|不发|算了)", value):
        return _clean_value(value)
    if field == "topic" and not re.search(r"(?:取消|不发|算了)", value):
        return _clean_value(value).lstrip("#")
    return None
