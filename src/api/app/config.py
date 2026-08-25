from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.time_zone import validate_iana_time_zone


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "HomeCare Twin API"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    allow_dev_actor_header: bool = True
    cors_origins: str = "http://localhost:5173"
    database_url: str = "sqlite+pysqlite:///./homecare-dev.sqlite3"
    request_id_header: str = "X-Request-ID"
    cursor_signing_key: str = "dev-only-change-me"
    default_household_time_zone: str = "UTC"
    outbox_poll_seconds: float = 2.0
    outbox_batch_size: int = 100
    outbox_stale_seconds: int = 300
    care_plan_poll_seconds: float = Field(default=30.0, ge=5, le=3600)
    file_root: str = "./data/files"
    master_data_root: str = "./data/master-data"
    master_data_approved_versions: str = ""
    max_upload_bytes: int = 10 * 1024 * 1024
    vision_model_version: str = "unavailable"
    ocr_version: str = "unavailable"
    vision_adapter_signing_key: str = "dev-only-change-me"
    vision_adapter_allowlist: str = "homecare-local-vision"
    vision_quality_config_version: str = "opencv-quality-demo-v2-lenient-exposure"
    # Keep strict rejection as the safe default.  The local demo can switch
    # this off to make quality metrics advisory while OCR integration is being
    # tuned.
    vision_quality_enforce_retake: bool = True
    # HCT-414-D2: short-video upper bound and capability switch.  The flag also
    # drives the /meta/capabilities declaration so mobile clients can fail
    # closed and hide the video entry when the server lacks the ability.
    vision_video_max_duration_seconds: int = Field(default=30, gt=0, le=600)
    vision_video_tasks_enabled: bool = True
    # HCT-439: uploaded videos are temporary evidence.  Keep a conservative
    # default and let operators lengthen the window without changing code.
    vision_video_retention_seconds: int = Field(default=86_400, ge=3_600, le=2_592_000)
    vision_video_cleanup_batch_size: int = Field(default=100, ge=1, le=1_000)
    # HCT-441: asynchronous workers claim jobs with a bounded lease.  An
    # expired lease is eligible for another worker, while repeated failures
    # eventually become a visible timeout instead of staying stuck in running.
    vision_worker_lease_seconds: int = Field(default=900, ge=30, le=86_400)
    vision_worker_max_attempts: int = Field(default=3, ge=1, le=10)
    vision_worker_claim_batch_size: int = Field(default=10, ge=1, le=100)
    vision_quality_min_width: int = 640
    vision_quality_min_height: int = 480
    vision_quality_min_blur_variance: float = 80.0
    vision_quality_min_mean_luminance: float = 45.0
    vision_quality_max_mean_luminance: float = 220.0
    vision_quality_max_dark_ratio: float = 0.45
    vision_quality_max_bright_ratio: float = 0.60
    vision_quality_max_glare_ratio: float = 0.35
    vision_quality_min_edge_density: float = 0.005
    vision_quality_min_subject_area_ratio: float = 0.08
    vision_quality_max_border_touch_ratio: float = 0.50
    biometric_encryption_key: str = "dev-only-biometric-key-change-me"
    # Local YuNet + SFace ONNX cache for HCT-425 v3 face embeddings.  Weights
    # stay outside git; first use may download from OpenCV Zoo when enabled.
    face_model_dir: str = "./models/face"
    face_model_auto_download: bool = True
    # Calibrate with scripts/calibrate_face_thresholds.py on local camera sets.
    face_match_threshold_sface: float = Field(default=0.40, ge=0.20, le=0.95)
    face_match_margin_sface: float = Field(default=0.05, ge=0.01, le=0.30)
    face_require_pose_liveness: bool = True
    ruleset_version: str = "rules-v0"
    knowledge_version: str = "knowledge-v0"
    embedding_version: str = "unavailable"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "unavailable"
    ollama_timeout_seconds: float = 30.0
    # HCT-430: the orchestrator and every model call stay local.  Public web
    # search is an explicitly opt-in, redacted tool and remains disabled by
    # default so HCT-004's default-deny posture is preserved.
    agent_orchestration_enabled: bool = True
    agent_web_search_enabled: bool = False
    # duckduckgo_html: parse the HTML endpoint; searxng: JSON API on the same URL.
    agent_web_search_provider: str = "duckduckgo_html"
    agent_web_search_url: str = "https://html.duckduckgo.com/html/"
    agent_web_search_timeout_seconds: float = Field(default=8.0, gt=0, le=20)
    agent_web_search_max_results: int = Field(default=5, ge=1, le=10)
    agent_web_search_allowed_domains: str = ""
    # Short TTL cache for redacted web-search queries (seconds). 0 disables cache.
    agent_web_search_cache_ttl_seconds: float = Field(default=180.0, ge=0, le=3600)
    # Minimum seconds between outbound search calls from this process (0 = off).
    agent_web_search_min_interval_seconds: float = Field(default=1.0, ge=0, le=60)
    # HCT-442: optional loopback Ollama classifier merged with lexicon (default off).
    agent_classifier_enabled: bool = False
    agent_classifier_timeout_seconds: float = Field(default=3.0, gt=0, le=15)
    # Session-scoped in-process cache for authorised local retrieval results.
    agent_retrieval_cache_ttl_seconds: float = Field(default=120.0, ge=0, le=3600)
    weather_adapter: str = "disabled"
    weather_provider: str = "generic"
    weather_api_url: str = ""
    weather_api_timeout_seconds: float = Field(default=3.0, gt=0, le=10)
    weather_default_city_code: str = ""
    weather_default_district_code: str = ""
    weather_location_whitelist: str = ""
    weather_cache_ttl_seconds: float = Field(default=600.0, ge=0, le=86400)
    weather_stale_ttl_seconds: float = Field(default=21600.0, ge=0, le=604800)
    weather_min_request_interval_seconds: float = Field(default=1.0, ge=0, le=60)
    weather_retry_attempts: int = Field(default=2, ge=1, le=3)
    weather_retry_backoff_seconds: float = Field(default=0.1, ge=0, le=2)
    weather_ruleset_version: str = "weather-actions-v1"
    egress_default_deny: bool = True
    egress_weather_whitelist: str = ""
    log_mask_enabled: bool = True
    upload_allowed_extensions: str = ".jpg,.jpeg,.png,.pdf,.mp4,.mov"
    upload_max_size_bytes: int = 10 * 1024 * 1024
    # Comma-separated actor ids allowed to read ``internal`` knowledge docs.
    # Empty means internal docs are creator-only (plus household/member scopes).
    knowledge_admin_actors: str = ""
    # Comma-separated actor ids allowed to activate/rollback model releases.
    # Empty means only the binding creator may govern that release.
    model_release_admin_actors: str = ""

    @field_validator("default_household_time_zone")
    @classmethod
    def validate_default_household_time_zone(cls, value: str) -> str:
        try:
            return validate_iana_time_zone(value)
        except ValueError as exc:
            raise ValueError("DEFAULT_HOUSEHOLD_TIME_ZONE_INVALID") from exc

    @model_validator(mode="after")
    def reject_unsafe_production_configuration(self) -> "Settings":
        """Prevent the local demo auth stores from being deployed as production.

        Password/PIN/face challenges and bearer sessions are intentionally
        process-local in this phase.  Starting with ``APP_ENV=production``
        would otherwise make a restart silently log everyone out and would
        retain development trust shortcuts.  Fail closed until the database
        session store, rotation and CSRF deployment work is delivered.
        """

        if self.app_env.strip().casefold() not in {"prod", "production"}:
            return self

        problems: list[str] = ["database-backed session persistence is not implemented"]
        if self.allow_dev_actor_header:
            problems.append("ALLOW_DEV_ACTOR_HEADER must be false")
        if self.cursor_signing_key in {"", "dev-only-change-me"}:
            problems.append("CURSOR_SIGNING_KEY must be replaced")
        if self.vision_adapter_signing_key in {"", "dev-only-change-me"}:
            problems.append("VISION_ADAPTER_SIGNING_KEY must be replaced")
        if self.biometric_encryption_key in {"", "dev-only-biometric-key-change-me"}:
            problems.append("BIOMETRIC_ENCRYPTION_KEY must be replaced")
        if not self.egress_default_deny:
            problems.append("EGRESS_DEFAULT_DENY must remain true")
        if self.agent_web_search_enabled and not self.agent_web_search_allowed_domain_set:
            problems.append("AGENT_WEB_SEARCH_ALLOWED_DOMAINS is required when search is enabled")
        if problems:
            raise ValueError("PRODUCTION_CONFIGURATION_BLOCKED: " + "; ".join(problems))
        return self

    @property
    def upload_allowed_ext_set(self) -> set[str]:
        return {
            ext.strip().lower() for ext in self.upload_allowed_extensions.split(",") if ext.strip()
        }

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def master_data_approved_version_set(self) -> set[str]:
        return {
            item.strip() for item in self.master_data_approved_versions.split(",") if item.strip()
        }

    @property
    def vision_adapter_allowlist_set(self) -> set[str]:
        return {item.strip() for item in self.vision_adapter_allowlist.split(",") if item.strip()}

    @property
    def weather_location_whitelist_set(self) -> set[str]:
        return {
            item.strip() for item in self.weather_location_whitelist.split(",") if item.strip()
        }

    @property
    def agent_web_search_allowed_domain_set(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.agent_web_search_allowed_domains.split(",")
            if item.strip()
        }

    @property
    def knowledge_admin_actor_set(self) -> set[str]:
        return {
            item.strip() for item in self.knowledge_admin_actors.split(",") if item.strip()
        }

    @property
    def model_release_admin_actor_set(self) -> set[str]:
        return {
            item.strip()
            for item in self.model_release_admin_actors.split(",")
            if item.strip()
        }

    def vision_quality_thresholds(self):
        from ai.vision.quality_gate import QualityThresholds

        return QualityThresholds(
            min_width=self.vision_quality_min_width,
            min_height=self.vision_quality_min_height,
            min_blur_variance=self.vision_quality_min_blur_variance,
            min_mean_luminance=self.vision_quality_min_mean_luminance,
            max_mean_luminance=self.vision_quality_max_mean_luminance,
            max_dark_ratio=self.vision_quality_max_dark_ratio,
            max_bright_ratio=self.vision_quality_max_bright_ratio,
            max_glare_ratio=self.vision_quality_max_glare_ratio,
            min_edge_density=self.vision_quality_min_edge_density,
            min_subject_area_ratio=self.vision_quality_min_subject_area_ratio,
            max_border_touch_ratio=self.vision_quality_max_border_touch_ratio,
            config_version=self.vision_quality_config_version,
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
