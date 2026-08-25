"""Calendar-based seasonal care framing for the teaching assistant.

These notes are lifestyle / seasonal context only.  They must never invent a
live outbreak name or count as medical evidence; virus-specific claims still
require approved knowledge chunks or gated web-search references.
"""

from __future__ import annotations

from datetime import UTC, datetime


def seasonal_care_context(*, when: datetime | None = None) -> str:
    """Return a short seasonal framing string for the current local month."""
    moment = when or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    # Teaching demo defaults to China-local seasonality.
    local = moment.astimezone()
    month = local.month

    if month in (3, 4, 5):
        return (
            "【季节情境】眼下多为冬春或春季换季，温差大、早晚凉，家庭成员容易着凉或"
            "出现鼻塞咳嗽等不适。回答时可先共情换季辛苦，再提醒增减衣物、通风休息；"
            "若本地知识或已授权联网参考提到近期高发呼吸道情况，可温和转述为参考，"
            "但不要编造具体病毒名或病例数。"
        )
    if month in (6, 7, 8):
        return (
            "【季节情境】眼下多为夏季，空调房与室外温差易让人觉得「热伤风」或肠胃不适。"
            "回答时可关心是否吹风受凉、补水休息；结合知识卡说明常见非处方资料时语气亲切，"
            "不要把季节感受说成确诊。"
        )
    if month in (9, 10, 11):
        return (
            "【季节情境】眼下多为秋冬换季，空气干燥、温差加大，咽痒咳嗽和感冒样不适更常见。"
            "回答时可先体谅换季不适，提醒保暖加湿与作息；若有已审核知识或联网参考提到"
            "季节性呼吸道流行，可作一般性提醒，禁止捏造「最近正在暴发某某病毒」。"
        )
    return (
        "【季节情境】眼下多为冬季，室内外温差大，家庭照护里常会遇到受凉、流感样不适的担心。"
        "回答时语气温暖具体：关心保暖、休息与是否有过敏史；结合知识卡说明常见资料，"
        "不把季节性不适写成诊断，也不编造流行疫情细节。"
    )


def seasonal_care_hint(*, when: datetime | None = None) -> str:
    """Return a short, user-facing seasonal care sentence.

    Unlike :func:`seasonal_care_context` (which is written as model
    instructions), this text can be shown to a family member directly.
    It stays at the lifestyle level: no diagnosis, no drug names, no
    outbreak claims.
    """
    moment = when or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    month = moment.astimezone().month

    if month in (3, 4, 5):
        return (
            "眼下正值换季，早晚温差大，容易着凉或觉得鼻塞咳嗽；"
            "可以先注意增减衣物、保持通风和充分休息。"
        )
    if month in (6, 7, 8):
        return (
            "夏天空调房和室外温差大，容易觉得鼻塞或有点「热伤风」；"
            "可以先避免冷风直吹、适当补水休息，观察是否缓解。"
        )
    if month in (9, 10, 11):
        return (
            "秋冬换季空气干燥、温差加大，咽痒咳嗽和感冒样不适更常见；"
            "可以先注意保暖加湿、规律作息，观察症状变化。"
        )
    return (
        "冬天室内外温差大，容易受凉出现感冒样不适；"
        "可以先注意保暖休息、适当通风，观察症状变化。"
    )
