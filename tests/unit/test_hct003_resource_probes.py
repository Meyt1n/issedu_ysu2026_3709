import json
from pathlib import Path
from urllib.error import URLError

import pytest
from ai.vision.resource_probe import probe_visual_sample
from sqlalchemy.exc import SQLAlchemyError

from app.resource_probes import probe_mysql, probe_ollama

FIXTURE = Path("tests/fixtures/hct003/visual_probe_sample.json")


class FakeScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one(self) -> object:
        return self.value


class FakeConnection:
    values = {
        "SELECT 1": 1,
        "SELECT VERSION()": "8.4.7",
        "SELECT @@character_set_database": "utf8mb4",
        "SELECT @@collation_database": "utf8mb4_unicode_ci",
        "SELECT @@session.time_zone": "+00:00",
        "SELECT version_num FROM alembic_version": "0002_allow_pending_health_events",
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()": 6,
    }

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: object) -> FakeScalarResult:
        return FakeScalarResult(self.values[str(statement)])


class FakeEngine:
    def connect(self) -> FakeConnection:
        return FakeConnection()

    def dispose(self) -> None:
        return None


class UnmigratedConnection(FakeConnection):
    def execute(self, statement: object) -> FakeScalarResult:
        if "alembic_version" in str(statement):
            raise SQLAlchemyError("Table 'homecare.alembic_version' does not exist")
        return super().execute(statement)


class UnmigratedEngine(FakeEngine):
    def connect(self) -> UnmigratedConnection:
        return UnmigratedConnection()


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_mysql_probe_reports_migration_and_hides_credentials() -> None:
    report = probe_mysql(
        "mysql+pymysql://private-user:private-password@db:3306/homecare?charset=utf8mb4",
        engine_factory=lambda _url: FakeEngine(),
        migration_head_loader=lambda: "0002_allow_pending_health_events",
    )

    serialized = json.dumps(report)
    assert report["status"] == "ok"
    assert report["checks"] == {
        "connected": True,
        "mysql_8_4": True,
        "utf8mb4": True,
        "utc_timezone": True,
        "migration_at_head": True,
    }
    assert report["database"]["migration_current"] == "0002_allow_pending_health_events"
    assert "private-user" not in serialized
    assert "private-password" not in serialized


def test_mysql_probe_returns_actionable_unavailable_result() -> None:
    def unavailable(_url: str) -> FakeEngine:
        raise SQLAlchemyError("connection refused")

    report = probe_mysql(
        "mysql+pymysql://homecare:secret@localhost:3306/homecare",
        engine_factory=unavailable,
    )

    assert report["status"] == "degraded"
    assert report["reason_code"] == "database_unavailable"
    assert report["action"] == "start_mysql_then_run_alembic_upgrade_head"
    assert "secret" not in json.dumps(report)


def test_mysql_probe_distinguishes_unmigrated_schema() -> None:
    report = probe_mysql(
        "mysql+pymysql://homecare:secret@localhost:3307/homecare",
        engine_factory=lambda _url: UnmigratedEngine(),
    )

    assert report["status"] == "degraded"
    assert report["reason_code"] == "database_schema_not_ready"
    assert report["action"] == "run_alembic_upgrade_head_and_check_schema"


def test_visual_probe_uses_fixed_sample_and_reports_resources() -> None:
    report = probe_visual_sample(FIXTURE)

    assert report["status"] == "ok"
    assert report["scope"] == "quality_gate_only"
    assert report["sample"]["synthetic"] is True
    assert report["sample"]["sha256"]
    assert report["image"] == {"width": 8, "height": 8, "channels": 1}
    assert report["metrics"]["sharpness_laplacian_variance"] > 0
    assert report["resources"]["elapsed_ms"] >= 0
    assert report["resources"]["rss_after_mib"] > 0
    assert "medicine_identity" not in report


def test_ollama_probe_validates_structured_local_response() -> None:
    response = {
        "model": "qwen2.5:0.5b",
        "response": json.dumps({"status": "ok", "message": "local probe ready"}),
        "done": True,
        "total_duration": 125_000_000,
        "eval_count": 7,
    }

    def local_opener(request: object, _timeout: float) -> FakeHttpResponse:
        if str(request.full_url).endswith("/api/version"):
            return FakeHttpResponse({"version": "0.20.2"})
        if str(request.full_url).endswith("/api/ps"):
            return FakeHttpResponse(
                {"models": [{"name": "qwen2.5:0.5b", "size": 1024, "size_vram": 512}]}
            )
        return FakeHttpResponse(response)

    report = probe_ollama(
        "http://127.0.0.1:11434",
        "qwen2.5:0.5b",
        opener=local_opener,
    )

    assert report["status"] == "ok"
    assert report["network_scope"] == "loopback_only"
    assert report["output"] == {"status": "ok", "message": "local probe ready"}
    assert report["resources"]["ollama_total_duration_ms"] == 125.0
    assert report["resources"]["model_size_mib"] == 0.001
    assert report["resources"]["model_vram_mib"] == 0.0


def test_ollama_probe_degrades_without_cloud_fallback() -> None:
    def unavailable(_request: object, _timeout: float) -> FakeHttpResponse:
        raise URLError("connection refused")

    report = probe_ollama(
        "http://localhost:11434",
        "qwen2.5:0.5b",
        opener=unavailable,
    )

    assert report["status"] == "degraded"
    assert report["reason_code"] == "ollama_unavailable"
    assert report["fallback"] == "structured_core_only"
    assert report["cloud_fallback"] is False
    assert "connection refused" in report["detail"]


@pytest.mark.parametrize(
    "base_url",
    ["https://api.example.com", "http://192.0.2.10:11434", "ftp://localhost:11434"],
)
def test_ollama_probe_rejects_non_loopback_or_non_http_endpoints(base_url: str) -> None:
    with pytest.raises(ValueError, match="loopback HTTP"):
        probe_ollama(base_url, "qwen2.5:0.5b")


def test_hct003_evidence_documents_and_boundaries_are_present() -> None:
    root = Path(__file__).resolve().parents[2]
    story = (root / "docs/stories/HCT-003-资源原型与技术选型.md").read_text(encoding="utf-8")
    adr = (root / "docs/decisions/0004-HCT003资源原型与分档基线.md").read_text(encoding="utf-8")
    review = (root / "docs/reviews/HCT-003-资源原型与技术选型评审记录.md").read_text(
        encoding="utf-8"
    )
    deployment = (root / "docs/本地部署与Demo操作指南.md").read_text(encoding="utf-8")

    assert "[#40](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/40)" in story
    assert "NFR-04、NFR-05、NFR-06" in story
    assert "不训练或发布 YOLO、OCR、Embedding、LoRA 或量化模型" in story
    assert "MySQL `8.4`" in adr and "OpenCV CPU" in adr and "回环 Ollama" in adr
    assert "P2/资源" in review and "structured_core_only" in review
    assert "hct003_probe.py" in deployment
    assert "不能把资源探针当作完整产品" in deployment
