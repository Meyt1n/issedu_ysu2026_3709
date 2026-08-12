from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    outbox_poll_seconds: float = 2.0
    outbox_batch_size: int = 100
    outbox_stale_seconds: int = 300
    file_root: str = "./data/files"
    master_data_root: str = "./data/master-data"
    master_data_approved_versions: str = ""
    max_upload_bytes: int = 10 * 1024 * 1024
    vision_model_version: str = "unavailable"
    ocr_version: str = "unavailable"
    vision_adapter_signing_key: str = "dev-only-change-me"
    vision_adapter_allowlist: str = "homecare-local-vision"
    vision_quality_config_version: str = "opencv-quality-demo-v1"
    vision_quality_min_width: int = 640
    vision_quality_min_height: int = 480
    vision_quality_min_blur_variance: float = 80.0
    vision_quality_min_mean_luminance: float = 45.0
    vision_quality_max_mean_luminance: float = 220.0
    vision_quality_max_dark_ratio: float = 0.45
    vision_quality_max_bright_ratio: float = 0.35
    vision_quality_max_glare_ratio: float = 0.15
    vision_quality_min_edge_density: float = 0.005
    vision_quality_min_subject_area_ratio: float = 0.08
    vision_quality_max_border_touch_ratio: float = 0.50
    ruleset_version: str = "rules-v0"
    knowledge_version: str = "knowledge-v0"
    embedding_version: str = "unavailable"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "unavailable"
    ollama_timeout_seconds: float = 30.0
    weather_adapter: str = "disabled"
    weather_api_url: str = ""
    weather_api_timeout_seconds: float = 3.0
    egress_default_deny: bool = True
    egress_weather_whitelist: str = ""
    log_mask_enabled: bool = True
    upload_allowed_extensions: str = ".jpg,.jpeg,.png,.pdf,.mp4,.mov"
    upload_max_size_bytes: int = 10 * 1024 * 1024

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
