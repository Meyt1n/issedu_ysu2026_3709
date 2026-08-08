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
    file_root: str = "./data/files"
    max_upload_bytes: int = 10 * 1024 * 1024
    vision_model_version: str = "unavailable"
    ocr_version: str = "unavailable"
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

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
