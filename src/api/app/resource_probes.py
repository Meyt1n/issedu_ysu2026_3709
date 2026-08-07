from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import psutil
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

MIB = 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parents[3]


class OllamaHandshake(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    message: Literal["local probe ready"]


def _rss_mib() -> float:
    return psutil.Process().memory_info().rss / MIB


def _resource_metrics(started: float, rss_before: float) -> dict[str, float]:
    rss_after = _rss_mib()
    host_memory = psutil.virtual_memory()
    return {
        "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        "rss_before_mib": round(rss_before, 3),
        "rss_after_mib": round(rss_after, 3),
        "rss_delta_mib": round(rss_after - rss_before, 3),
        "host_total_memory_mib": round(host_memory.total / MIB, 3),
        "host_available_memory_mib": round(host_memory.available / MIB, 3),
    }


def _migration_head() -> str:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    return str(ScriptDirectory.from_config(config).get_current_head())


def _create_mysql_engine(database_url: str) -> Any:
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=300)


def _safe_database_target(database_url: str) -> tuple[dict[str, Any], list[str]]:
    parsed = make_url(database_url)
    if not parsed.drivername.startswith("mysql"):
        raise ValueError("MySQL probe requires a mysql SQLAlchemy URL")
    target = {
        "driver": parsed.drivername,
        "host": parsed.host,
        "port": parsed.port or 3306,
        "database": parsed.database,
    }
    sensitive = [value for value in (parsed.username, parsed.password) if value]
    return target, sensitive


def _safe_error_detail(error: Exception, sensitive: list[str]) -> str:
    detail = f"{type(error).__name__}: {error}"
    for value in sensitive:
        detail = detail.replace(value, "***")
    return detail[:500]


def probe_mysql(
    database_url: str,
    *,
    engine_factory: Callable[[str], Any] = _create_mysql_engine,
    migration_head_loader: Callable[[], str] = _migration_head,
) -> dict[str, Any]:
    target, sensitive = _safe_database_target(database_url)
    rss_before = _rss_mib()
    started = perf_counter()
    engine = None
    try:
        engine = engine_factory(database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
            try:
                server_version = str(connection.execute(text("SELECT VERSION()")).scalar_one())
                charset = str(
                    connection.execute(text("SELECT @@character_set_database")).scalar_one()
                )
                collation = str(
                    connection.execute(text("SELECT @@collation_database")).scalar_one()
                )
                timezone = str(
                    connection.execute(text("SELECT @@session.time_zone")).scalar_one()
                )
                migration_current = str(
                    connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one()
                )
                table_count = int(
                    connection.execute(
                        text(
                            "SELECT COUNT(*) FROM information_schema.tables "
                            "WHERE table_schema = DATABASE()"
                        )
                    ).scalar_one()
                )
            except SQLAlchemyError as error:
                return {
                    "probe": "mysql_foundation",
                    "status": "degraded",
                    "reason_code": "database_schema_not_ready",
                    "detail": _safe_error_detail(error, sensitive),
                    "action": "run_alembic_upgrade_head_and_check_schema",
                    "target": target,
                    "resources": _resource_metrics(started, rss_before),
                }
        migration_head = migration_head_loader()
    except SQLAlchemyError as error:
        return {
            "probe": "mysql_foundation",
            "status": "degraded",
            "reason_code": "database_unavailable",
            "detail": _safe_error_detail(error, sensitive),
            "action": "start_mysql_then_run_alembic_upgrade_head",
            "target": target,
            "resources": _resource_metrics(started, rss_before),
        }
    finally:
        if engine is not None:
            engine.dispose()

    checks = {
        "connected": True,
        "mysql_8_4": server_version.startswith("8.4."),
        "utf8mb4": charset == "utf8mb4" and collation.startswith("utf8mb4"),
        "utc_timezone": timezone in {"+00:00", "UTC"},
        "migration_at_head": migration_current == migration_head,
    }
    report: dict[str, Any] = {
        "probe": "mysql_foundation",
        "status": "ok" if all(checks.values()) else "review",
        "target": target,
        "checks": checks,
        "database": {
            "server_version": server_version,
            "character_set": charset,
            "collation": collation,
            "session_timezone": timezone,
            "migration_current": migration_current,
            "migration_head": migration_head,
            "table_count": table_count,
        },
        "resources": _resource_metrics(started, rss_before),
    }
    if report["status"] != "ok":
        report.update(
            reason_code="database_invariant_failed",
            action="check_mysql_version_charset_timezone_and_alembic_revision",
        )
    return report


def _default_opener(request: Request, timeout: float) -> Any:
    return urlopen(request, timeout=timeout)


def _loopback_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Ollama probe requires a loopback HTTP endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Ollama probe requires a loopback HTTP endpoint without credentials")
    return base_url.rstrip("/")


def _json_request(url: str, payload: dict[str, Any] | None = None) -> Request:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    return Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )


def _read_json(response: Any) -> dict[str, Any]:
    payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Ollama response must be a JSON object")
    return payload


def _ollama_degraded(
    *,
    reason_code: str,
    detail: str,
    action: str,
    started: float,
    rss_before: float,
) -> dict[str, Any]:
    return {
        "probe": "ollama_structured_output",
        "status": "degraded",
        "reason_code": reason_code,
        "detail": detail[:500],
        "action": action,
        "network_scope": "loopback_only",
        "fallback": "structured_core_only",
        "cloud_fallback": False,
        "resources": _resource_metrics(started, rss_before),
    }


def probe_ollama(
    base_url: str,
    model: str,
    *,
    timeout: float = 30.0,
    opener: Callable[[Request, float], Any] = _default_opener,
) -> dict[str, Any]:
    local_base_url = _loopback_base_url(base_url)
    rss_before = _rss_mib()
    started = perf_counter()
    if not model.strip() or model == "unavailable":
        return _ollama_degraded(
            reason_code="ollama_model_not_configured",
            detail="OLLAMA_MODEL is not configured with a local model name",
            action="set_ollama_model_to_an_installed_local_model",
            started=started,
            rss_before=rss_before,
        )

    schema = OllamaHandshake.model_json_schema()
    generate_payload = {
        "model": model,
        "prompt": (
            'Return only this technical handshake JSON: '
            '{"status":"ok","message":"local probe ready"}'
        ),
        "stream": False,
        "format": schema,
        "options": {"temperature": 0, "num_predict": 32},
    }
    try:
        with opener(_json_request(f"{local_base_url}/api/version"), timeout) as response:
            version_payload = _read_json(response)
        with opener(
            _json_request(f"{local_base_url}/api/generate", generate_payload), timeout
        ) as response:
            generation = _read_json(response)
        output = OllamaHandshake.model_validate_json(str(generation["response"]))
        with opener(_json_request(f"{local_base_url}/api/ps"), timeout) as response:
            loaded_models = _read_json(response).get("models", [])
    except HTTPError as error:
        reason_code = "ollama_model_unavailable" if error.code == 404 else "ollama_http_error"
        action = (
            "install_or_select_the_declared_local_model"
            if error.code == 404
            else "inspect_local_ollama_service_logs"
        )
        return _ollama_degraded(
            reason_code=reason_code,
            detail=f"HTTP {error.code}: {error.reason}",
            action=action,
            started=started,
            rss_before=rss_before,
        )
    except (URLError, TimeoutError, OSError) as error:
        return _ollama_degraded(
            reason_code="ollama_unavailable",
            detail=f"{type(error).__name__}: {error}",
            action="start_local_ollama_and_verify_the_loopback_endpoint",
            started=started,
            rss_before=rss_before,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError) as error:
        return _ollama_degraded(
            reason_code="ollama_invalid_response",
            detail=f"{type(error).__name__}: {error}",
            action="verify_model_json_schema_support_and_response_format",
            started=started,
            rss_before=rss_before,
        )

    resources = _resource_metrics(started, rss_before)
    resources.update(
        ollama_total_duration_ms=round(float(generation.get("total_duration", 0)) / 1_000_000, 3),
        eval_count=int(generation.get("eval_count", 0)),
    )
    loaded_model = next(
        (
            item
            for item in loaded_models
            if item.get("name") == model or item.get("model") == model
        ),
        {},
    )
    resources.update(
        model_size_mib=round(float(loaded_model.get("size", 0)) / MIB, 3),
        model_vram_mib=round(float(loaded_model.get("size_vram", 0)) / MIB, 3),
    )
    return {
        "probe": "ollama_structured_output",
        "status": "ok",
        "network_scope": "loopback_only",
        "cloud_fallback": False,
        "server_version": version_payload.get("version", "unknown"),
        "model": generation.get("model", model),
        "schema": "OllamaHandshake/v1",
        "output": output.model_dump(),
        "resources": resources,
    }
