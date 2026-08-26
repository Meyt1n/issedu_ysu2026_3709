"""Tests for allowlisted knowledge crawl → staging → promote pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient


def test_crawl_fixtures_to_staging_and_promote(tmp_path: Path, monkeypatch) -> None:
    from app import knowledge_crawl as crawl

    staging = tmp_path / "staging"
    monkeypatch.setattr(crawl, "STAGING_ROOT", staging)
    monkeypatch.setattr(crawl, "RUNS_PATH", staging / "crawl_runs.jsonl")

    report = crawl.run_crawl(live=False)
    assert report["fetched"] >= 4
    assert report["auto_ingest"] is False
    items = crawl.list_staging()
    assert len(items) >= 4
    source_id = items[0]["source_id"]

    # Unchanged re-crawl keeps hash.
    again = crawl.run_crawl(live=False)
    assert again["unchanged"] >= 1

    reviewed = crawl.mark_staging_reviewed(
        source_id, reviewer="tester", notes="ok", approve=True
    )
    assert reviewed["status"] == "approved"

    incoming = tmp_path / "incoming"
    promoted = crawl.promote_approved_staging(actor_id="tester", target_root=incoming)
    assert promoted["document_count"] >= 1
    assert (incoming / "正式知识清单.crawl.json").is_file()


def test_due_only_skips_fresh_sources(tmp_path: Path, monkeypatch) -> None:
    from app import knowledge_crawl as crawl

    staging = tmp_path / "staging"
    monkeypatch.setattr(crawl, "STAGING_ROOT", staging)
    monkeypatch.setattr(crawl, "RUNS_PATH", staging / "crawl_runs.jsonl")

    first = crawl.run_crawl(live=False)
    assert first["fetched"] >= 1
    due = crawl.run_crawl(live=False, due_only=True)
    assert due["fetched"] == 0

    # Force one meta to look stale.
    meta_path = next((staging / "meta").glob("*.json"))
    meta = __import__("json").loads(meta_path.read_text(encoding="utf-8"))
    meta["fetched_at"] = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    meta_path.write_text(__import__("json").dumps(meta), encoding="utf-8")
    refreshed = crawl.run_crawl(live=False, due_only=True)
    assert refreshed["fetched"] >= 1


def test_reject_and_host_allowlist() -> None:
    from app.knowledge_crawl import crawl_source

    try:
        crawl_source(
            {
                "id": "blocked",
                "title": "blocked",
                "url": "https://evil.example/page",
                "license": "x",
                "enabled": True,
            },
            policy={
                "max_bytes_per_page": 1000,
                "user_agent": "test",
                "allowed_hosts": ["www.cdc.gov"],
            },
            live=True,
        )
        raise AssertionError("expected HOST_NOT_ALLOWLISTED")
    except ValueError as exc:
        assert "HOST_NOT_ALLOWLISTED" in str(exc)


def test_live_remote_requires_enabled_flag() -> None:
    from app.knowledge_crawl import crawl_source

    try:
        crawl_source(
            {
                "id": "blocked",
                "title": "blocked",
                "url": "https://www.cdc.gov/page",
                "license": "x",
                "enabled": False,
            },
            policy={
                "max_bytes_per_page": 1000,
                "user_agent": "test",
                "allowed_hosts": ["www.cdc.gov"],
            },
            live=True,
        )
        raise AssertionError("expected SOURCE_DISABLED")
    except ValueError as exc:
        assert "SOURCE_DISABLED" in str(exc)


def test_knowledge_crawl_api_steward_only(client: TestClient) -> None:
    denied = client.get(
        "/api/v1/knowledge/crawl/staging",
        headers={"X-Actor-Id": "stranger"},
    )
    assert denied.status_code == 403
    # The reason code is a UI contract: the web panel keys the "需要知识管理员"
    # guidance on this detail instead of showing a silent empty list.
    assert denied.json()["detail"] == "KNOWLEDGE_STEWARD_REQUIRED"

    status = client.get(
        "/api/v1/knowledge/crawl/status",
        headers={"X-Actor-Id": "demo-parent", "X-Access-Purpose": "family-care"},
    )
    assert status.status_code == 200, status.text
    assert status.json()["auto_ingest"] is False

    allowed = client.post(
        "/api/v1/knowledge/crawl/run",
        headers={"X-Actor-Id": "demo-parent", "X-Access-Purpose": "family-care"},
    )
    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["fetched"] >= 1
    assert body["auto_ingest"] is False

    source_id = body["results"][0]["source_id"]
    rejected = client.post(
        f"/api/v1/knowledge/crawl/staging/{source_id}/review?reject=true&notes=no",
        headers={"X-Actor-Id": "demo-parent", "X-Access-Purpose": "family-care"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_knowledge_crawl_config_missing_is_structured_503(
    client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    """Deployments without docs/knowledge/crawl must not degrade to a bare 500.

    The reason code is a UI contract: the web panel shows a rebuild-the-image
    hint for ``KNOWLEDGE_CRAWL_CONFIG_MISSING`` instead of claiming the whole
    API is unavailable.
    """
    from app import knowledge_crawl as crawl

    monkeypatch.setattr(crawl, "ALLOWLIST_PATH", tmp_path / "absent" / "allowlist.json")

    headers = {"X-Actor-Id": "demo-parent", "X-Access-Purpose": "family-care"}
    status = client.get("/api/v1/knowledge/crawl/status", headers=headers)
    assert status.status_code == 503, status.text
    assert status.json()["detail"] == "KNOWLEDGE_CRAWL_CONFIG_MISSING"

    run = client.post("/api/v1/knowledge/crawl/run", headers=headers)
    assert run.status_code == 503, run.text
    assert run.json()["detail"] == "KNOWLEDGE_CRAWL_CONFIG_MISSING"

    # Steward gating still applies before any config diagnostics leak out.
    denied = client.get(
        "/api/v1/knowledge/crawl/status", headers={"X-Actor-Id": "stranger"}
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "KNOWLEDGE_STEWARD_REQUIRED"


def test_staging_detail_returns_markdown_and_change_flags(
    tmp_path: Path, monkeypatch
) -> None:
    from app import knowledge_crawl as crawl

    staging = tmp_path / "staging"
    monkeypatch.setattr(crawl, "STAGING_ROOT", staging)
    monkeypatch.setattr(crawl, "RUNS_PATH", staging / "crawl_runs.jsonl")

    first = crawl.run_crawl(live=False)
    assert first["new_sources"] == first["fetched"] >= 1
    source_id = first["results"][0]["source_id"]
    assert first["results"][0]["first_fetch"] is True

    detail = crawl.get_staging_detail(source_id)
    assert detail["source_id"] == source_id
    assert detail["content_available"] is True
    assert detail["content_markdown"].startswith("# ")
    assert "staging 草稿" in detail["content_markdown"]
    assert detail["is_formal_evidence"] is False
    assert "不是正式检索证据" in detail["disclaimer"]

    again = crawl.run_crawl(live=False)
    assert again["new_sources"] == 0
    assert again["unchanged"] == again["fetched"]
    refreshed = crawl.get_staging_detail(source_id)
    assert refreshed["unchanged"] is True
    assert refreshed["first_fetch"] is False

    # Missing and traversal-style ids are both a plain not-found.
    for bad_id in ("absent-source", "../meta", "a/b"):
        try:
            crawl.get_staging_detail(bad_id)
            raise AssertionError("expected STAGING_NOT_FOUND")
        except FileNotFoundError as exc:
            assert "STAGING_NOT_FOUND" in str(exc)


def test_simulate_fixture_update_marks_changed_and_resets_review(
    tmp_path: Path, monkeypatch
) -> None:
    from app import knowledge_crawl as crawl

    staging = tmp_path / "staging"
    monkeypatch.setattr(crawl, "STAGING_ROOT", staging)
    monkeypatch.setattr(crawl, "RUNS_PATH", staging / "crawl_runs.jsonl")

    crawl.run_crawl(live=False)
    items = crawl.list_staging()
    source_id = items[0]["source_id"]
    crawl.mark_staging_reviewed(source_id, reviewer="tester", approve=True)
    assert crawl.get_staging_detail(source_id)["status"] == "approved"

    bump = crawl.simulate_fixture_update(actor_id="tester")
    assert bump["ok"] is True
    assert bump["teaching_demo"] is True
    assert bump["auto_ingest"] is False
    assert any(entry["source_id"] == source_id for entry in bump["bumped"])
    # Repository fixtures are never modified — only runtime overlays.
    assert not any(
        "demo-bump" in path.read_text(encoding="utf-8")
        for path in crawl.FIXTURES_ROOT.glob("*.html")
    )

    changed = crawl.run_crawl(live=False)
    assert changed["changed"] == changed["fetched"] >= 1
    detail = crawl.get_staging_detail(source_id)
    assert detail["status"] == "draft"  # approval requires a fresh review
    assert detail["unchanged"] is False
    assert detail["demo_override"] is True
    assert "教学演示模拟更新" in detail["content_markdown"]

    # A second bump increments the version so每次演示都能再次触发变更。
    second = crawl.simulate_fixture_update(actor_id="tester")
    bumped = {entry["source_id"]: entry["demo_bump"] for entry in second["bumped"]}
    assert bumped[source_id] == 2

    # Reset restores the pristine fixture content on the next crawl.
    reset = crawl.simulate_fixture_update(actor_id="tester", reset=True)
    assert reset["reset"] is True
    assert reset["cleared"]
    restored = crawl.run_crawl(live=False)
    assert restored["changed"] >= 1
    restored_detail = crawl.get_staging_detail(source_id)
    assert restored_detail["demo_override"] is False
    assert "教学演示模拟更新" not in restored_detail["content_markdown"]


def test_new_teaching_fixtures_registered_in_allowlist() -> None:
    from app.knowledge_crawl import FIXTURES_ROOT, load_allowlist

    allowlist = load_allowlist()
    ids = {source["id"] for source in allowlist["sources"]}
    assert {"fixture-seasonal-home-care", "fixture-med-disposal"} <= ids
    for name in ("seasonal-home-care.html", "med-disposal.html"):
        text = (FIXTURES_ROOT / name).read_text(encoding="utf-8")
        assert "本地夹具" in text
        assert "不构成诊断或用药建议" in text


def test_staging_detail_and_simulate_update_api_contracts(
    client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    from app import knowledge_crawl as crawl

    staging = tmp_path / "staging"
    monkeypatch.setattr(crawl, "STAGING_ROOT", staging)
    monkeypatch.setattr(crawl, "RUNS_PATH", staging / "crawl_runs.jsonl")

    steward = {"X-Actor-Id": "demo-parent", "X-Access-Purpose": "family-care"}
    stranger = {"X-Actor-Id": "stranger"}

    # Steward gate applies to both new endpoints.
    assert (
        client.get("/api/v1/knowledge/crawl/staging/any-id", headers=stranger).status_code
        == 403
    )
    assert (
        client.post("/api/v1/knowledge/crawl/simulate-update", headers=stranger).status_code
        == 403
    )

    run = client.post("/api/v1/knowledge/crawl/run", headers=steward)
    assert run.status_code == 200, run.text
    assert run.json()["new_sources"] >= 1
    source_id = run.json()["results"][0]["source_id"]

    detail = client.get(
        f"/api/v1/knowledge/crawl/staging/{source_id}", headers=steward
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["content_markdown"].startswith("# ")
    assert body["is_formal_evidence"] is False

    missing = client.get(
        "/api/v1/knowledge/crawl/staging/absent-source", headers=steward
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "STAGING_NOT_FOUND"

    bump = client.post("/api/v1/knowledge/crawl/simulate-update", headers=steward)
    assert bump.status_code == 200, bump.text
    assert bump.json()["teaching_demo"] is True
    assert bump.json()["auto_ingest"] is False

    changed = client.post("/api/v1/knowledge/crawl/run", headers=steward)
    assert changed.status_code == 200
    assert changed.json()["changed"] >= 1

    reset = client.post(
        "/api/v1/knowledge/crawl/simulate-update?reset=true", headers=steward
    )
    assert reset.status_code == 200
    assert reset.json()["reset"] is True


def test_knowledge_crawl_api_allows_configured_admin(client: TestClient) -> None:
    """Actors in KNOWLEDGE_ADMIN_ACTORS are stewards without a demo prefix."""
    from app.config import get_settings

    settings = get_settings()
    previous = settings.knowledge_admin_actors
    settings.knowledge_admin_actors = "ops-knowledge-admin"
    try:
        denied = client.get(
            "/api/v1/knowledge/crawl/status",
            headers={"X-Actor-Id": "someone-else"},
        )
        allowed = client.get(
            "/api/v1/knowledge/crawl/status",
            headers={"X-Actor-Id": "ops-knowledge-admin"},
        )
    finally:
        settings.knowledge_admin_actors = previous

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["auto_ingest"] is False
