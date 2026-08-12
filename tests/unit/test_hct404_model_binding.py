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
