"""Integration tests for HCT-404 model version binding API endpoints."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.model_binding import create_binding


class TestCreateBindingAPI:
    def test_create_returns_201(self, client: TestClient):
        resp = client.post("/api/v1/model-version-bindings", json={
            "model_id": "api-test-model-v1",
            "dataset_version": "ds-v1",
            "fixed_set_hash": "abc123",
            "comparison_report_hash": "rep-hash",
        }, headers={"X-Actor-Id": "alice"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["model_id"] == "api-test-model-v1"
        assert data["release_status"] == "inactive"


class TestActivateBindingAPI:
    def test_activate_transitions_to_active(self, client: TestClient, db_session: Session):
        resp = client.post("/api/v1/model-version-bindings", json={
            "model_id": "act-api-v1",
            "dataset_version": "ds-v1",
            "fixed_set_hash": "abc",
            "comparison_report_hash": "rep-hash",
        }, headers={"X-Actor-Id": "alice"})
        binding_id = resp.json()["id"]

        resp2 = client.post(
            f"/api/v1/model-version-bindings/{binding_id}/activate",
            json={"approved_by": "alice"},
            headers={"X-Actor-Id": "alice"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["release_status"] == "active"

    def test_activate_without_report_fails(self, client: TestClient):
        resp = client.post("/api/v1/model-version-bindings", json={
            "model_id": "act-no-rpt-v1",
            "dataset_version": "ds-v1",
            "fixed_set_hash": "abc",
        }, headers={"X-Actor-Id": "alice"})
        binding_id = resp.json()["id"]

        resp2 = client.post(
            f"/api/v1/model-version-bindings/{binding_id}/activate",
            json={"approved_by": "alice"},
            headers={"X-Actor-Id": "alice"},
        )
        assert resp2.status_code == 422

    def test_hct404_activate_without_real_release_evidence_fails(self, client: TestClient):
        resp = client.post(
            "/api/v1/model-version-bindings",
            json={
                "model_id": "hct404-vision-v2",
                "dataset_version": "candidate-v2",
                "fixed_set_hash": "a" * 64,
                "comparison_report_hash": "b" * 64,
            },
            headers={"X-Actor-Id": "alice"},
        )
        binding_id = resp.json()["id"]
        resp2 = client.post(
            f"/api/v1/model-version-bindings/{binding_id}/activate",
            json={"approved_by": "alice"},
            headers={"X-Actor-Id": "alice"},
        )
        assert resp2.status_code == 422
        assert resp2.json()["detail"] == "HCT404_FORMAL_RELEASE_REQUIRED"

    def test_activate_deactivates_previous(self, client: TestClient, db_session: Session):
        # First binding
        r1 = client.post("/api/v1/model-version-bindings", json={
            "model_id": "deact-chain-v1",
            "dataset_version": "ds-v1",
            "fixed_set_hash": "abc",
            "comparison_report_hash": "r1",
        }, headers={"X-Actor-Id": "alice"})
        b1_id = r1.json()["id"]
        client.post(f"/api/v1/model-version-bindings/{b1_id}/activate",
                    json={"approved_by": "alice"}, headers={"X-Actor-Id": "alice"})

        # Second binding
        r2 = client.post("/api/v1/model-version-bindings", json={
            "model_id": "deact-chain-v1",
            "dataset_version": "ds-v2",
            "fixed_set_hash": "def",
            "comparison_report_hash": "r2",
        }, headers={"X-Actor-Id": "alice"})
        b2_id = r2.json()["id"]
        client.post(f"/api/v1/model-version-bindings/{b2_id}/activate",
                    json={"approved_by": "alice"}, headers={"X-Actor-Id": "alice"})

        # b1 should now be inactive
        r3 = client.get(f"/api/v1/model-version-bindings/{b1_id}", headers={"X-Actor-Id": "alice"})
        assert r3.json()["release_status"] == "inactive"

        # b2 should be active
        r4 = client.get(f"/api/v1/model-version-bindings/{b2_id}", headers={"X-Actor-Id": "alice"})
        assert r4.json()["release_status"] == "active"


class TestRollbackBindingAPI:
    def test_rollback_sets_revoked(self, client: TestClient):
        r1 = client.post("/api/v1/model-version-bindings", json={
            "model_id": "rb-api-v1",
            "dataset_version": "ds-v1",
            "fixed_set_hash": "abc",
            "comparison_report_hash": "r1",
        }, headers={"X-Actor-Id": "alice"})
        b_id = r1.json()["id"]
        client.post(f"/api/v1/model-version-bindings/{b_id}/activate",
                    json={"approved_by": "alice"}, headers={"X-Actor-Id": "alice"})

        r2 = client.post(f"/api/v1/model-version-bindings/{b_id}/rollback",
                         json={"reason": "bug"}, headers={"X-Actor-Id": "alice"})
        assert r2.status_code == 200
        assert r2.json()["release_status"] == "revoked"

    def test_hct404_rollback_requires_evidence_hash(self, client: TestClient):
        hashes = {
            key: value * 64
            for key, value in (
                ("evidence", "a"),
                ("gate", "b"),
                ("model", "c"),
                ("fixed", "d"),
                ("comparison", "e"),
                ("rollback", "f"),
                ("approval", "0"),
            )
        }
        thresholds = {
            "hct404_release_evidence_required": True,
            "hct404_release_evidence_schema": "hct404-model-release-evidence/v1",
            "hct404_release_status": "ALLOW_FORMAL_RELEASE",
            "hct404_release_evidence_sha256": hashes["evidence"],
            "hct404_release_gate_sha256": hashes["gate"],
            "hct404_model_artifact_sha256": hashes["model"],
            "hct404_fixed_set_sha256": hashes["fixed"],
            "hct404_comparison_report_sha256": hashes["comparison"],
            "hct404_rollback_evidence_sha256": hashes["rollback"],
            "hct404_approval_sha256": hashes["approval"],
        }
        response = client.post(
            "/api/v1/model-version-bindings",
            json={
                "model_id": "hct404-vision-v2",
                "dataset_version": "candidate-v2",
                "fixed_set_hash": hashes["fixed"],
                "comparison_report_hash": hashes["comparison"],
                "release_evidence_hash": hashes["evidence"],
                "safety_thresholds": thresholds,
            },
            headers={"X-Actor-Id": "alice"},
        )
        binding_id = response.json()["id"]
        client.post(
            f"/api/v1/model-version-bindings/{binding_id}/activate",
            json={"approved_by": "alice"},
            headers={"X-Actor-Id": "alice"},
        )
        missing = client.post(
            f"/api/v1/model-version-bindings/{binding_id}/rollback",
            json={"reason": "release drill"},
            headers={"X-Actor-Id": "alice"},
        )
        assert missing.status_code == 422
        assert missing.json()["detail"] == "HCT404_ROLLBACK_EVIDENCE_REQUIRED"
        rolled_back = client.post(
            f"/api/v1/model-version-bindings/{binding_id}/rollback",
            json={"reason": "release drill", "evidence_hash": hashes["rollback"]},
            headers={"X-Actor-Id": "alice"},
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()["rollback_evidence_hash"] == hashes["rollback"]

    def test_rollback_reactivates_previous(self, client: TestClient):
        # First binding → activate
        r1 = client.post("/api/v1/model-version-bindings", json={
            "model_id": "rb-chain-api-v1",
            "dataset_version": "ds-v1",
            "fixed_set_hash": "abc",
            "comparison_report_hash": "r1",
        }, headers={"X-Actor-Id": "alice"})
        b1_id = r1.json()["id"]
        client.post(f"/api/v1/model-version-bindings/{b1_id}/activate",
                    json={"approved_by": "alice"}, headers={"X-Actor-Id": "alice"})

        # Second binding → activate (deactivates b1)
        r2 = client.post("/api/v1/model-version-bindings", json={
            "model_id": "rb-chain-api-v1",
            "dataset_version": "ds-v2",
            "fixed_set_hash": "def",
            "comparison_report_hash": "r2",
        }, headers={"X-Actor-Id": "alice"})
        b2_id = r2.json()["id"]
        client.post(f"/api/v1/model-version-bindings/{b2_id}/activate",
                    json={"approved_by": "alice"}, headers={"X-Actor-Id": "alice"})

        # Rollback b2
        client.post(f"/api/v1/model-version-bindings/{b2_id}/rollback",
                    json={"reason": "rollback test"}, headers={"X-Actor-Id": "alice"})

        # b1 should be active again
        r3 = client.get(f"/api/v1/model-version-bindings/{b1_id}", headers={"X-Actor-Id": "alice"})
        assert r3.json()["release_status"] == "active"

        # b2 should be revoked
        r4 = client.get(f"/api/v1/model-version-bindings/{b2_id}", headers={"X-Actor-Id": "alice"})
        assert r4.json()["release_status"] == "revoked"


class TestActiveModelVersionEndpoint:
    def test_returns_config_fallback(self, client: TestClient):
        resp = client.get("/api/v1/meta/active-model-version")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_model_version" in data
        assert data["source"] == "config"

    def test_returns_binding_when_active(self, client: TestClient, db_session: Session):
        # Create and activate a binding
        b = create_binding(
            db_session,
            model_id="meta-active-v1",
            dataset_version="ds-v1",
            export_manifest_id=None,
            fixed_set_hash="abc",
            comparison_report_hash="r1",
            created_by="alice",
        )
        db_session.commit()
        from app.model_binding import activate_binding
        activate_binding(db_session, b, approved_by="bob")
        db_session.commit()

        resp = client.get("/api/v1/meta/active-model-version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_model_version"] == "meta-active-v1"
        assert data["source"] == "binding"


class TestListBindingsAPI:
    def test_list_all(self, client: TestClient, db_session: Session):
        create_binding(
            db_session, model_id="list-api-v1", dataset_version="ds1",
            export_manifest_id=None, fixed_set_hash="h1", created_by="alice",
        )
        db_session.commit()

        resp = client.get("/api/v1/model-version-bindings", headers={"X-Actor-Id": "alice"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_filter_by_model_id(self, client: TestClient, db_session: Session):
        create_binding(
            db_session, model_id="filter-api-v1", dataset_version="ds1",
            export_manifest_id=None, fixed_set_hash="h1", created_by="alice",
        )
        db_session.commit()

        resp = client.get(
            "/api/v1/model-version-bindings?model_id=filter-api-v1",
            headers={"X-Actor-Id": "alice"},
        )
        data = resp.json()
        assert all(b["model_id"] == "filter-api-v1" for b in data)


class TestComparisonEndpoint:
    def test_returns_comparison_info(self, client: TestClient):
        r1 = client.post("/api/v1/model-version-bindings", json={
            "model_id": "cmp-api-v1",
            "dataset_version": "ds-v1",
            "fixed_set_hash": "abc",
            "comparison_report_hash": "cmp-hash-xyz",
        }, headers={"X-Actor-Id": "alice"})
        b_id = r1.json()["id"]

        resp = client.get(
            f"/api/v1/model-version-bindings/{b_id}/comparison",
            headers={"X-Actor-Id": "alice"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["comparison_report_hash"] == "cmp-hash-xyz"
        assert data["model_id"] == "cmp-api-v1"
