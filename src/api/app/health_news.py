"""Proactive health-news cards for the home screen (seasonal local baseline).

HCT-444: calendar teaching reminders with assistant jump prompts.
HCT-445: remote whitelist cards are merged by ``health_news_adapter``; this
module remains the local-only catalog and shared item schema.  Cards never
invent a live outbreak name or case count.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

DISCLAIMER = (
    "公开资讯与季节提醒仅供教学演示，不是疫情通报或诊断依据。"
    "来自白名单站点的标题与摘要保持原文摘录；本系统不编造病毒名或病例数。"
    "具体不适请咨询医生或药师。"
)


class HealthNewsItem(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    kind: Literal["seasonal_tip", "remote"] = "seasonal_tip"
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=400)
    tag: str = Field(min_length=1, max_length=40)
    chat_prompt: str = Field(min_length=1, max_length=240)
    source: Literal["seasonal_calendar", "remote_whitelist"] = "seasonal_calendar"
    source_name: str | None = Field(default=None, max_length=80)
    source_url: str | None = Field(default=None, max_length=500)
    published_at: datetime | None = None
    fetched_at: datetime | None = None

    @field_validator("source_url")
    @classmethod
    def https_only_source_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not value.lower().startswith("https://"):
            raise ValueError("source_url must be https")
        return value


class HealthNewsResponse(BaseModel):
    """Legacy/local shape kept for seasonal-only helpers and older callers."""

    generated_at: datetime
    season: str
    items: list[HealthNewsItem]
    disclaimer: str = DISCLAIMER
    status: str = "local_only"
    cache_status: str = "none"
    fetched_at: datetime | None = None
    degraded_reason: str | None = None
    sources_attempted: list[str] = Field(default_factory=list)


def season_key_for(month: int) -> str:
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def _season_key(month: int) -> str:
    return season_key_for(month)


def seasonal_catalog() -> dict[str, list[dict[str, Any]]]:
    return {
        "spring": [
            {
                "id": "spring-transition-cold",
                "kind": "seasonal_tip",
                "title": "换季温差大，留意着凉与鼻塞咳嗽",
                "summary": (
                    "冬春或春季早晚凉、白天暖，家人容易因温差着凉。"
                    "可先增减衣物、保持通风与休息；若想了解常见感冒样不适的一般资料，"
                    "可点进本地助手，结合过敏史一起看看。"
                ),
                "tag": "换季照护",
                "chat_prompt": "换季容易着凉，感冒样不适一般可以了解哪些常用药资料？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
            {
                "id": "spring-respiratory-season",
                "kind": "seasonal_tip",
                "title": "春季呼吸道不适更常见，不必自行「确诊病毒」",
                "summary": (
                    "换季时鼻塞、咽痒、低热等不适更常见，但首页不会编造具体病毒名或病例数。"
                    "若家里有人持续不适，建议先记录症状时间，再向医生或药师咨询。"
                ),
                "tag": "季节提醒",
                "chat_prompt": "最近换季，呼吸道不适要注意什么？有哪些一般性居家照护提醒？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
        ],
        "summer": [
            {
                "id": "summer-ac-chill",
                "kind": "seasonal_tip",
                "title": "空调房温差大，小心「热伤风」样不适",
                "summary": (
                    "夏季室内外温差大，吹风受凉后可能出现鼻塞、喉咙不适。"
                    "可先调整出风口、补水休息；点进助手可按知识卡了解常见非处方资料说明。"
                ),
                "tag": "夏季照护",
                "chat_prompt": "夏天吹空调后有点鼻塞，一般可以了解哪些用药资料？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
            {
                "id": "summer-hydration-gi",
                "kind": "seasonal_tip",
                "title": "暑热时节关注补水与肠胃负担",
                "summary": (
                    "高温下更容易脱水和饮食不规律。首页提醒偏生活照护，不是诊断；"
                    "若出现持续腹泻或高热，请及时联系医务人员。"
                ),
                "tag": "生活提醒",
                "chat_prompt": "夏天容易肠胃不舒服，居家照护上有哪些一般性注意点？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
        ],
        "autumn": [
            {
                "id": "autumn-transition-dry",
                "kind": "seasonal_tip",
                "title": "秋冬换季空气干燥，咽痒咳嗽更常见",
                "summary": (
                    "秋冬换季温差加大、空气偏干，家人可能出现咽痒或感冒样不适。"
                    "可先保暖加湿、规律作息；想对照知识卡了解常见资料时，可点进本地助手。"
                ),
                "tag": "换季照护",
                "chat_prompt": "秋冬换季容易咳嗽咽痒，一般可以了解哪些用药或照护资料？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
            {
                "id": "autumn-flu-like-caution",
                "kind": "seasonal_tip",
                "title": "季节性呼吸道流行期：只做一般提醒，不替代诊疗",
                "summary": (
                    "秋冬常被称作流感样不适高发时段，但本页不会声称「正在暴发某某病毒」。"
                    "有发热、呼吸困难等加重表现时，请优先联系医务人员。"
                ),
                "tag": "季节提醒",
                "chat_prompt": "换季时流感样不适要注意什么？怎样向本地助手提问更合适？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
            {
                "id": "autumn-dry-air",
                "kind": "seasonal_tip",
                "title": "空气偏干时，把舒适度放进每日照护清单",
                "summary": (
                    "秋季室内空气变干时，可以关注饮水、休息和环境舒适度。"
                    "这些是一般生活提醒；若不适持续或加重，请及时联系医务人员。"
                ),
                "tag": "居家环境",
                "chat_prompt": "秋季空气偏干，居家环境和日常照护一般可以注意什么？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
            {
                "id": "autumn-window-airing",
                "kind": "seasonal_tip",
                "title": "每天短时通风，让室内空气保持流动",
                "summary": (
                    "天气允许时可以安排短时开窗通风，并根据家人感受调整时间。"
                    "通风提醒不替代针对具体症状的医学判断。"
                ),
                "tag": "居家习惯",
                "chat_prompt": "秋季家里怎样安排短时通风和保暖，比较适合作为日常提醒？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
            {
                "id": "autumn-gentle-walk",
                "kind": "seasonal_tip",
                "title": "天气舒适时，把活动拆成一小段",
                "summary": (
                    "外出前先看天气和家人状态，把活动安排成轻松、可随时结束的小段。"
                    "如有明显不适，不要勉强活动，并优先咨询医务人员。"
                ),
                "tag": "日常活动",
                "chat_prompt": "秋天天气舒适时，家庭日常活动可以怎样安排得更稳妥？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
            {
                "id": "autumn-family-checkin",
                "kind": "seasonal_tip",
                "title": "晚间做一次家庭照护小复盘",
                "summary": (
                    "可以在固定时间简单回顾当天的饮水、休息和已确认事项，"
                    "把需要继续观察的问题记下来，方便之后与医生或药师沟通。"
                ),
                "tag": "家庭协作",
                "chat_prompt": "家庭每天做照护小复盘时，可以记录哪些一般信息？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
        ],
        "winter": [
            {
                "id": "winter-warmth-flu-like",
                "kind": "seasonal_tip",
                "title": "冬季保暖与流感样不适的居家提醒",
                "summary": (
                    "冬季室内外温差大，受凉后不适更常见。先做好保暖与休息；"
                    "若想了解一般性用药资料，可点进助手并结合家里的过敏史核对。"
                ),
                "tag": "冬季照护",
                "chat_prompt": "冬天容易感冒，一般可以了解哪些常用药资料？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
            {
                "id": "winter-indoor-air",
                "kind": "seasonal_tip",
                "title": "室内通风与密切接触时的照护习惯",
                "summary": (
                    "冬季门窗紧闭时，注意短时通风与手卫生。这是教学向生活提醒，"
                    "不是疫情通报；持续高热或呼吸困难请及时就医。"
                ),
                "tag": "生活提醒",
                "chat_prompt": "冬天家里通风和防着凉有哪些一般性建议？",
                "source": "seasonal_calendar",
                "source_name": "本地季节日历",
            },
        ],
    }


def build_seasonal_items(*, when: datetime | None = None) -> list[HealthNewsItem]:
    moment = when or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone()
    season = season_key_for(local.month)
    return [HealthNewsItem.model_validate(row) for row in seasonal_catalog()[season]]


def build_health_news(*, when: datetime | None = None) -> HealthNewsResponse:
    """Return always-on local seasonal cards (no network)."""
    moment = when or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone()
    season = season_key_for(local.month)
    items = build_seasonal_items(when=local)
    return HealthNewsResponse(
        generated_at=local,
        season=season,
        items=items,
        status="local_only",
        cache_status="none",
    )
