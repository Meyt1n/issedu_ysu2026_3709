import io
import json
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from check_http_health import HealthCheckError, check_health_endpoint

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeHealthResponse:
    def __init__(
        self,
        payload: object = None,
        status: int = 200,
        raw_body: bytes | None = None,
    ) -> None:
        self.status = status
        body = raw_body if raw_body is not None else json.dumps(payload).encode("utf-8")
        self._body = io.BytesIO(body)

    def read(self) -> bytes:
        return self._body.read()

    def __enter__(self) -> "FakeHealthResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def read_repo_file(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_cross_platform_start_scripts_expose_lifecycle_commands() -> None:
    powershell = read_repo_file("scripts/start.ps1")
    shell = read_repo_file("scripts/start.sh")

    for command in ("setup", "up", "health", "down", "check"):
        assert command in powershell
        assert command in shell
    assert "uv sync --frozen" in powershell
    assert "uv sync --frozen" in shell
    assert "docker compose up -d --build --wait" in powershell
    assert "docker compose up -d --build --wait" in shell
    assert "docker compose down" in powershell
    assert "docker compose down" in shell
    assert "/api/v1/health/db" in powershell
    assert "/api/v1/health/db" in shell
    assert "check_http_health.py" in powershell
    assert "check_http_health.py" in shell
    assert "docker compose down --volumes" not in powershell
    assert "docker compose down --volumes" not in shell


def test_http_health_checker_requires_ok_json() -> None:
    payload = check_health_endpoint(
        "API",
        "http://127.0.0.1:8000/health",
        opener=lambda *_args, **_kwargs: FakeHealthResponse({"status": "ok"}),
    )

    assert payload["status"] == "ok"


def test_http_health_checker_rejects_non_ok_status() -> None:
    with pytest.raises(HealthCheckError, match="status 不是 ok"):
        check_health_endpoint(
            "MySQL",
            "http://localhost:8000/api/v1/health/db",
            opener=lambda *_args, **_kwargs: FakeHealthResponse({"status": "degraded"}),
        )


def test_http_health_checker_rejects_non_200_response() -> None:
    with pytest.raises(HealthCheckError, match="HTTP 503"):
        check_health_endpoint(
            "Web",
            "http://127.0.0.1:8080/health",
            opener=lambda *_args, **_kwargs: FakeHealthResponse({"status": "ok"}, status=503),
        )


def test_http_health_checker_rejects_invalid_json() -> None:
    with pytest.raises(HealthCheckError, match="JSON 解析失败"):
        check_health_endpoint(
            "API",
            "http://127.0.0.1:8000/health",
            opener=lambda *_args, **_kwargs: FakeHealthResponse(raw_body=b"not-json"),
        )


def test_http_health_checker_rejects_non_loopback_url() -> None:
    with pytest.raises(HealthCheckError, match="只允许本机 HTTP 地址"):
        check_health_endpoint("API", "https://example.com/health")


def test_compose_has_locatable_health_checks_for_all_services() -> None:
    compose = read_repo_file("docker-compose.yml")

    assert all(f"  {service}:" in compose for service in ("db", "api", "web"))
    assert compose.count("healthcheck:") == 3
    assert "condition: service_healthy" in compose
    assert "wget --spider" in compose or "urllib.request" in compose


def test_container_images_are_pinned_to_verified_digests() -> None:
    compose = read_repo_file("docker-compose.yml")
    api_dockerfile = read_repo_file("docker/api.Dockerfile")
    web_dockerfile = read_repo_file("docker/web.Dockerfile")

    assert "mysql:8.4@sha256:" in compose
    assert "python:3.11-slim@sha256:" in api_dockerfile
    assert "node:22-alpine@sha256:" in web_dockerfile
    assert "nginx:1.27-alpine@sha256:" in web_dockerfile


def test_env_example_uses_non_secret_placeholders() -> None:
    env_example = read_repo_file(".env.example")

    assert "MYSQL_PASSWORD=change-me" in env_example
    assert "MYSQL_ROOT_PASSWORD=change-me-root" in env_example
    assert "sk-" not in env_example
    assert "glpat-" not in env_example
    assert "REVIEW_API_KEY=" not in env_example


def test_alembic_has_a_single_head() -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0002_allow_pending_health_events"]


def test_reproduction_guides_describe_the_verified_lifecycle() -> None:
    guide = read_repo_file("docs/本地部署与Demo操作指南.md")
    readme = read_repo_file("README.md")

    for command in ("setup", "up", "health", "down"):
        assert f"start.ps1 {command}" in guide or f"start.sh {command}" in guide
    assert "干净环境复现记录" in guide
    assert "完整 P0 业务" in readme
