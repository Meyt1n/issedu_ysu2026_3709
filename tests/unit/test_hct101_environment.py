from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]


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
