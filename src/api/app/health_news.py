"""Proactive seasonal health-news cards for the home screen.

Cards are generated from the local calendar (same family of logic as the
assistant seasonal framing).  They never invent a live outbreak name or
case count.  Each card carries a ``chat_prompt`` so the UI can jump into
the local assistant with a ready-made teaching question.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthNewsItem(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=400)
    tag: str = Field(min_length=1, max_length=40)
    chat_prompt: str = Field(min_length=1, max_length=240)
    source: Literal["seasonal_calendar"] = "seasonal_calendar"


class HealthNewsResponse(BaseModel):
    generated_at: datetime
    season: str
    items: list[HealthNewsItem]
    disclaimer: str = (
        "以上为教学演示用的季节照护提醒，不是疫情通报或诊断依据。"
        "具体不适请咨询医生或药师。"
    )


def _season_key(month: int) -> str:
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def build_health_news(*, when: datetime | None = None) -> HealthNewsResponse:
    """Return always-on home-screen health news for the current season."""
    moment = when or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone()
    season = _season_key(local.month)
    catalog: dict[str, list[dict[str, Any]]] = {
        "spring": [
            {
                "id": "spring-transition-cold",
                "title": "换季温差大，留意着凉与鼻塞咳嗽",
                "summary": (
                    "冬春或春季早晚凉、白天暖，家人容易因温差着凉。"
                    "可先增减衣物、保持通风与休息；若想了解常见感冒样不适的一般资料，"
                    "可点进本地助手，结合过敏史一起看看。"
                ),
                "tag": "换季照护",
                "chat_prompt": "换季容易着凉，感冒样不适一般可以了解哪些常用药资料？",
            },
            {
                "id": "spring-respiratory-season",
                "title": "春季呼吸道不适更常见，不必自行「确诊病毒」",
                "summary": (
                    "换季时鼻塞、咽痒、低热等不适更常见，但首页不会编造具体病毒名或病例数。"
                    "若家里有人持续不适，建议先记录症状时间，再向医生或药师咨询。"
                ),
                "tag": "季节提醒",
                "chat_prompt": "最近换季，呼吸道不适要注意什么？有哪些一般性居家照护提醒？",
            },
        ],
        "summer": [
            {
                "id": "summer-ac-chill",
                "title": "空调房温差大，小心「热伤风」样不适",
                "summary": (
                    "夏季室内外温差大，吹风受凉后可能出现鼻塞、喉咙不适。"
                    "可先调整出风口、补水休息；点进助手可按知识卡了解常见非处方资料说明。"
                ),
                "tag": "夏季照护",
                "chat_prompt": "夏天吹空调后有点鼻塞，一般可以了解哪些用药资料？",
            },
            {
                "id": "summer-hydration-gi",
                "title": "暑热时节关注补水与肠胃负担",
                "summary": (
                    "高温下更容易脱水和饮食不规律。首页提醒偏生活照护，不是诊断；"
                    "若出现持续腹泻或高热，请及时联系医务人员。"
                ),
                "tag": "生活提醒",
                "chat_prompt": "夏天容易肠胃不舒服，居家照护上有哪些一般性注意点？",
            },
        ],
        "autumn": [
            {
                "id": "autumn-transition-dry",
                "title": "秋冬换季空气干燥，咽痒咳嗽更常见",
                "summary": (
                    "秋冬换季温差加大、空气偏干，家人可能出现咽痒或感冒样不适。"
                    "可先保暖加湿、规律作息；想对照知识卡了解常见资料时，可点进本地助手。"
                ),
                "tag": "换季照护",
                "chat_prompt": "秋冬换季容易咳嗽咽痒，一般可以了解哪些用药或照护资料？",
            },
            {
                "id": "autumn-flu-like-caution",
                "title": "季节性呼吸道流行期：只做一般提醒，不替代诊疗",
                "summary": (
                    "秋冬常被称作流感样不适高发时段，但本页不会声称「正在暴发某某病毒」。"
                    "有发热、呼吸困难等加重表现时，请优先联系医务人员。"
                ),
                "tag": "季节提醒",
                "chat_prompt": "换季时流感样不适要注意什么？怎样向本地助手提问更合适？",
            },
        ],
        "winter": [
            {
                "id": "winter-warmth-flu-like",
                "title": "冬季保暖与流感样不适的居家提醒",
                "summary": (
                    "冬季室内外温差大，受凉后不适更常见。先做好保暖与休息；"
                    "若想了解一般性用药资料，可点进助手并结合家里的过敏史核对。"
                ),
                "tag": "冬季照护",
                "chat_prompt": "冬天容易感冒，一般可以了解哪些常用药资料？",
            },
            {
                "id": "winter-indoor-air",
                "title": "室内通风与密切接触时的照护习惯",
                "summary": (
                    "冬季门窗紧闭时，注意短时通风与手卫生。这是教学向生活提醒，"
                    "不是疫情通报；持续高热或呼吸困难请及时就医。"
                ),
                "tag": "生活提醒",
                "chat_prompt": "冬天家里通风和防着凉有哪些一般性建议？",
            },
        ],
    }
    items = [HealthNewsItem.model_validate(row) for row in catalog[season]]
    return HealthNewsResponse(generated_at=local, season=season, items=items)
