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
