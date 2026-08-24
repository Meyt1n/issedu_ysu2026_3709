"""Unit tests for HCT-404 model_binding module."""

import pytest
from sqlalchemy.orm import Session

from app.model_binding import (
    DEFAULT_SAFETY_THRESHOLDS,
    ModelVersionBinding,
    activate_binding,
    create_binding,
    list_bindings,
    resolve_active_model_version,
    rollback_binding,
)


class TestCreateBinding:
    def test_creates_inactive(self, db_session: Session):
        b = create_binding(
            db_session,
            model_id="test-model-v1",
            dataset_version="ds-v1",
            export_manifest_id=None,
            fixed_set_hash="abc123",
            created_by="alice",
        )
        db_session.commit()
        assert b.release_status == "inactive"
        assert b.model_id == "test-model-v1"

    def test_defaults_safety_thresholds(self, db_session: Session):
        b = create_binding(
            db_session,
            model_id="test-model-v2",
            dataset_version="ds-v1",
            export_manifest_id=None,
            fixed_set_hash="abc123",
            created_by="alice",
        )
        db_session.commit()
        assert b.safety_thresholds == DEFAULT_SAFETY_THRESHOLDS

    def test_custom_thresholds_override(self, db_session: Session):
        custom = {"min_map50": 0.80}
        b = create_binding(
            db_session,
            model_id="test-model-v3",
            dataset_version="ds-v1",
            export_manifest_id=None,
            fixed_set_hash="abc123",
            safety_thresholds=custom,
            created_by="alice",
        )
        db_session.commit()
        assert b.safety_thresholds == custom


class TestActivateBinding:
    def _setup(self, db_session: Session) -> ModelVersionBinding:
        b = create_binding(
            db_session,
            model_id="act-test-v1",
            dataset_version="ds-v1",
            export_manifest_id=None,
            fixed_set_hash="abc",
            comparison_report_hash="rep-hash-123",
            created_by="alice",
        )
        db_session.commit()
        return b

    def test_activate_sets_active(self, db_session: Session):
        b = self._setup(db_session)
        activate_binding(db_session, b, approved_by="bob")
        db_session.commit()
        assert b.release_status == "active"
        assert b.approved_by == "bob"

    def test_activate_requires_comparison_report(self, db_session: Session):
        b = create_binding(
            db_session,
            model_id="act-no-report",
            dataset_version="ds-v1",
            export_manifest_id=None,
            fixed_set_hash="abc",
            created_by="alice",
        )
        db_session.commit()
        with pytest.raises(ValueError, match="COMPARISON_REPORT_REQUIRED"):
            activate_binding(db_session, b, approved_by="bob")

    def test_hct203_candidate_requires_publication_evidence(self, db_session: Session):
        b = create_binding(
            db_session,
            model_id="hct-yolo11n-box-assist-experimental-v1.3",
            dataset_version="approved-v1",
            export_manifest_id=None,
            fixed_set_hash="fixed-v1",
            comparison_report_hash="report-v1",
            created_by="alice",
        )
        db_session.commit()
        with pytest.raises(ValueError, match="HCT203_PUBLICATION_REQUIRED"):
            activate_binding(db_session, b, approved_by="bob")

    def test_hct203_publication_evidence_allows_activation(self, db_session: Session):
        evidence = {
            "hct203_publication_status": "PUBLISHED_AUXILIARY_ONLY",
            "hct203_machine_gate_sha256": "a" * 64,
            "hct203_r3_review_sha256": "b" * 64,
        }
        b = create_binding(
            db_session,
            model_id="hct-yolo11n-box-assist-released-v1.0",
            dataset_version="approved-v1",
            export_manifest_id=None,
            fixed_set_hash="fixed-v1",
            safety_thresholds=evidence,
            comparison_report_hash="report-v1",
            created_by="alice",
        )
        db_session.commit()
        activate_binding(db_session, b, approved_by="bob")
        assert b.release_status == "active"

    def test_hct203_maintainer_waiver_evidence_allows_activation(self, db_session: Session):
        evidence = {
            "hct203_publication_status": "PUBLISHED_AUXILIARY_ONLY",
            "hct203_release_authority": "MAINTAINER_WAIVER",
            "hct203_machine_gate_sha256": "a" * 64,
            "hct203_waiver_sha256": "b" * 64,
        }
        b = create_binding(
            db_session,
            model_id="hct-yolo11n-box-assist-waiver-v1.3",
            dataset_version="candidate-v1",
            export_manifest_id=None,
            fixed_set_hash="candidate-v1",
            safety_thresholds=evidence,
            comparison_report_hash="report-v1",
            created_by="alice",
        )
        db_session.commit()
        activate_binding(db_session, b, approved_by="bob")
        assert b.release_status == "active"

    def test_hct404_formal_binding_requires_real_release_evidence(self, db_session: Session):
        b = create_binding(
            db_session,
            model_id="hct404-vision-v2",
            dataset_version="approved-fixed-v2",
            export_manifest_id=None,
            fixed_set_hash="a" * 64,
            comparison_report_hash="b" * 64,
            created_by="alice",
        )
        db_session.commit()
        with pytest.raises(ValueError, match="HCT404_FORMAL_RELEASE_REQUIRED"):
            activate_binding(db_session, b, approved_by="bob")

    def test_hct404_formal_binding_with_hash_chain_allows_activation(
        self, db_session: Session
    ):
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
        b = create_binding(
            db_session,
            model_id="hct404-vision-v2",
            dataset_version="approved-fixed-v2",
            export_manifest_id=None,
            fixed_set_hash=hashes["fixed"],
            safety_thresholds=thresholds,
            comparison_report_hash=hashes["comparison"],
            release_evidence_hash=hashes["evidence"],
            created_by="alice",
        )
        db_session.commit()
        activate_binding(db_session, b, approved_by="bob")
        assert b.release_status == "active"

    def test_hct404_formal_rollback_requires_reason_and_evidence(
        self, db_session: Session
    ):
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
        b = create_binding(
            db_session,
            model_id="hct404-vision-v2",
            dataset_version="approved-fixed-v2",
            export_manifest_id=None,
            fixed_set_hash=hashes["fixed"],
            safety_thresholds=thresholds,
            comparison_report_hash=hashes["comparison"],
            release_evidence_hash=hashes["evidence"],
            created_by="alice",
        )
        db_session.commit()
        activate_binding(db_session, b, approved_by="bob")
        db_session.commit()
        with pytest.raises(ValueError, match="HCT404_ROLLBACK_REASON_REQUIRED"):
            rollback_binding(db_session, b, actor_id="admin")
        rollback_binding(
            db_session,
            b,
            actor_id="admin",
            reason="release drill",
            evidence_hash=hashes["rollback"],
        )
        assert b.release_status == "revoked"
        assert b.rollback_evidence_hash == hashes["rollback"]

    def test_activate_deactivates_previous(self, db_session: Session):
        b1 = self._setup(db_session)
        activate_binding(db_session, b1, approved_by="bob")
        db_session.commit()

        b2 = create_binding(
            db_session,
            model_id="act-test-v1",  # same model_id
            dataset_version="ds-v2",
            export_manifest_id=None,
            fixed_set_hash="def",
            comparison_report_hash="rep-2",
            created_by="alice",
        )
        db_session.commit()
        activate_binding(db_session, b2, approved_by="charlie")
        db_session.commit()

        db_session.refresh(b1)
        assert b1.release_status == "inactive"
        assert b2.release_status == "active"

    def test_cannot_activate_revoked(self, db_session: Session):
        b = self._setup(db_session)
        activate_binding(db_session, b, approved_by="bob")
        db_session.commit()
        rollback_binding(db_session, b, actor_id="admin")
        db_session.commit()

        with pytest.raises(ValueError, match="BINDING_ALREADY_REVOKED"):
            activate_binding(db_session, b, approved_by="charlie")

    def test_cannot_activate_already_active(self, db_session: Session):
        b = self._setup(db_session)
        activate_binding(db_session, b, approved_by="bob")
        db_session.commit()

        with pytest.raises(ValueError, match="BINDING_ALREADY_ACTIVE"):
            activate_binding(db_session, b, approved_by="charlie")


class TestRollbackBinding:
    def _setup_active(self, db_session: Session) -> ModelVersionBinding:
        b = create_binding(
            db_session,
            model_id="rb-test-v1",
            dataset_version="ds-v1",
            export_manifest_id=None,
            fixed_set_hash="abc",
            comparison_report_hash="rep-hash",
            created_by="alice",
        )
        db_session.commit()
        activate_binding(db_session, b, approved_by="bob")
        db_session.commit()
        return b

    def test_rollback_sets_revoked(self, db_session: Session):
        b = self._setup_active(db_session)
        rollback_binding(db_session, b, actor_id="admin", reason="bug found")
        db_session.commit()
        assert b.release_status == "revoked"
        assert b.revoked_by == "admin"

    def test_rollback_binding_reactivates_previous(self, db_session: Session):
        # First binding
        b1 = create_binding(
            db_session,
            model_id="rb-chain-v1",
            dataset_version="ds-v1",
            export_manifest_id=None,
            fixed_set_hash="abc",
            comparison_report_hash="r1",
            created_by="alice",
        )
        db_session.commit()
        activate_binding(db_session, b1, approved_by="bob")
        db_session.commit()

        # Second binding (auto-deactivates b1)
        b2 = create_binding(
            db_session,
            model_id="rb-chain-v1",
            dataset_version="ds-v2",
            export_manifest_id=None,
            fixed_set_hash="def",
            comparison_report_hash="r2",
            created_by="alice",
        )
        db_session.commit()
        activate_binding(db_session, b2, approved_by="charlie")
        db_session.commit()

        # Rollback b2 → b1 reactivates
        rollback_binding(db_session, b2, actor_id="admin")
        db_session.commit()

        db_session.refresh(b2)
        db_session.refresh(b1)
        assert b2.release_status == "revoked"
        assert b1.release_status == "active"

    def test_cannot_rollback_non_active(self, db_session: Session):
        b = create_binding(
            db_session,
            model_id="rb-na-v1",
            dataset_version="ds-v1",
            export_manifest_id=None,
            fixed_set_hash="abc",
            comparison_report_hash="r1",
            created_by="alice",
        )
        db_session.commit()
        with pytest.raises(ValueError, match="BINDING_NOT_ACTIVE"):
            rollback_binding(db_session, b, actor_id="admin")


class TestResolveActiveVersion:
    def test_no_active_returns_none(self, db_session: Session):
        assert resolve_active_model_version(db_session) is None

    def test_resolves_active(self, db_session: Session):
        b = create_binding(
            db_session,
            model_id="resolve-v1",
            dataset_version="ds-v1",
            export_manifest_id=None,
            fixed_set_hash="abc",
            comparison_report_hash="r1",
            created_by="alice",
        )
        db_session.commit()
        activate_binding(db_session, b, approved_by="bob")
        db_session.commit()

        resolved = resolve_active_model_version(db_session)
        assert resolved == "resolve-v1"


class TestListBindings:
    def test_filter_by_model_id(self, db_session: Session):
        create_binding(
            db_session, model_id="list-a", dataset_version="ds1",
            export_manifest_id=None, fixed_set_hash="h1", created_by="alice",
        )
        create_binding(
            db_session, model_id="list-b", dataset_version="ds1",
            export_manifest_id=None, fixed_set_hash="h2", created_by="alice",
        )
        db_session.commit()
        assert len(list_bindings(db_session, model_id="list-a")) == 1

    def test_filter_by_status(self, db_session: Session):
        b = create_binding(
            db_session, model_id="list-c", dataset_version="ds1",
            export_manifest_id=None, fixed_set_hash="h1",
            comparison_report_hash="r1", created_by="alice",
        )
        db_session.commit()
        activate_binding(db_session, b, approved_by="bob")
        db_session.commit()
        assert len(list_bindings(db_session, release_status="active")) == 1
        assert len(list_bindings(db_session, release_status="inactive")) == 0
