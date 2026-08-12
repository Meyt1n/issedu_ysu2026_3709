"""Integration tests for HCT-208: correction diffs, hard samples,
training consent, and export manifests.

Requires database (uses the test SQLite fixture from conftest).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.hard_sample import (
    VALID_CATEGORIES,
    _canonical_hash,
    create_correction_diff,
    create_export_manifest,
    create_hard_sample,
    delete_hard_sample,
    get_export_manifest,
    get_hard_sample,
    get_training_consent,
    grant_training_consent,
    invalidate_export_manifest,
    list_correction_diffs,
    list_export_manifests,
    list_hard_samples,
    revoke_training_consent,
    update_hard_sample_status,
)
from app.models import HealthEvent, Household, Member


class TestCorrectionDiff:
    def test_create_diff_records_before_after(self, db_session: Session):
        household = Household(name="Test", created_by="alice")
        db_session.add(household)
        db_session.flush()

        member = Member(household_id=household.id, display_name="Member1", role="DEPENDENT")
        db_session.add(member)
        db_session.flush()

        event = HealthEvent(
            household_id=household.id,
            member_id=member.id,
            sequence_no=1,
            event_type="medication_confirmed",
            source="MANUAL_REVIEW",
            confirmation_status="CONFIRMED",
            payload={"drug_name": "OldName"},
            evidence={},
            created_by="alice",
            correlation_id="corr-1",
        )
        db_session.add(event)
        db_session.commit()

        diff = create_correction_diff(
            db_session,
            household_id=household.id,
            member_id=member.id,
            source_event_id=event.id,
            field_path="payload.drug_name",
            before_value="OldName",
            after_value="NewName",
            reason="OCR misread",
            evidence={"ocr_text": "NewName"},
            operator_actor_id="alice",
        )
        db_session.commit()

        assert diff.id is not None
        assert diff.version == 1
        assert diff.before_value == "OldName"
        assert diff.after_value == "NewName"
        assert diff.field_path == "payload.drug_name"

    def test_duplicate_diff_increments_version(self, db_session: Session):
        household = Household(name="Test", created_by="alice")
        db_session.add(household)
        db_session.flush()
        member = Member(household_id=household.id, display_name="M1", role="DEPENDENT")
        db_session.add(member)
        db_session.flush()
        event = HealthEvent(
            household_id=household.id, member_id=member.id, sequence_no=1,
            event_type="test", source="MANUAL", confirmation_status="CONFIRMED",
            payload={}, evidence={}, created_by="alice", correlation_id="c1",
        )
        db_session.add(event)
        db_session.commit()

        d1 = create_correction_diff(
            db_session, household_id=household.id, member_id=member.id,
            source_event_id=event.id, field_path="payload.x",
            before_value="A", after_value="B", reason="fix1",
            evidence={}, operator_actor_id="alice",
        )
        db_session.commit()
        d2 = create_correction_diff(
            db_session, household_id=household.id, member_id=member.id,
            source_event_id=event.id, field_path="payload.x",
            before_value="B", after_value="C", reason="fix2",
            evidence={}, operator_actor_id="alice",
        )
        db_session.commit()

        assert d1.version == 1
        assert d2.version == 2

    def test_list_diffs_by_event(self, db_session: Session):
        household = Household(name="Test", created_by="alice")
        db_session.add(household)
        db_session.flush()
        member = Member(household_id=household.id, display_name="M1", role="DEPENDENT")
        db_session.add(member)
        db_session.flush()
        event = HealthEvent(
            household_id=household.id, member_id=member.id, sequence_no=1,
            event_type="test", source="MANUAL", confirmation_status="CONFIRMED",
            payload={}, evidence={}, created_by="alice", correlation_id="c1",
        )
        db_session.add(event)
        db_session.commit()

        create_correction_diff(
            db_session, household_id=household.id, member_id=member.id,
            source_event_id=event.id, field_path="payload.a",
            before_value=None, after_value="X", reason="test",
            evidence={}, operator_actor_id="alice",
        )
        db_session.commit()

        diffs = list_correction_diffs(db_session, household.id, source_event_id=event.id)
        assert len(diffs) == 1
        assert diffs[0].source_event_id == event.id

    def test_source_event_not_found_raises(self, db_session: Session):
        household = Household(name="Test", created_by="alice")
        db_session.add(household)
        db_session.flush()
        member = Member(household_id=household.id, display_name="M1", role="DEPENDENT")
        db_session.add(member)
        db_session.commit()

        with pytest.raises(ValueError, match="SOURCE_EVENT_NOT_FOUND"):
            create_correction_diff(
                db_session, household_id=household.id, member_id=member.id,
                source_event_id="nonexistent", field_path="x",
                before_value=None, after_value="y", reason="test",
                evidence={}, operator_actor_id="alice",
            )


class TestHardSample:
    def _setup(self, db_session: Session) -> tuple[Household, Member, HealthEvent]:
        household = Household(name="Test", created_by="alice")
        db_session.add(household)
        db_session.flush()
        member = Member(household_id=household.id, display_name="M1", role="DEPENDENT")
        db_session.add(member)
        db_session.flush()
        event = HealthEvent(
            household_id=household.id, member_id=member.id, sequence_no=1,
            event_type="medication_confirmed", source="MANUAL_REVIEW",
            confirmation_status="CONFIRMED", payload={}, evidence={},
            created_by="alice", correlation_id="c1",
        )
        db_session.add(event)
        db_session.commit()
        return household, member, event

    def test_create_hard_sample_defaults_to_pending(self, db_session: Session):
        h, m, e = self._setup(db_session)
        sample = create_hard_sample(
            db_session, household_id=h.id, member_id=m.id,
            source_event_id=e.id, category="hard_font",
            note="test note", created_by="alice",
        )
        db_session.commit()
        assert sample.status == "pending"
        assert sample.category == "hard_font"

    def test_invalid_category_rejected(self, db_session: Session):
        h, m, e = self._setup(db_session)
        with pytest.raises(ValueError, match="INVALID_CATEGORY"):
            create_hard_sample(
                db_session, household_id=h.id, member_id=m.id,
                source_event_id=e.id, category="not_a_category",
                created_by="alice",
            )

    def test_approve_sample(self, db_session: Session):
        h, m, e = self._setup(db_session)
        sample = create_hard_sample(
            db_session, household_id=h.id, member_id=m.id,
            source_event_id=e.id, category="hard_layout", created_by="alice",
        )
        db_session.commit()

        updated = update_hard_sample_status(
            db_session, sample, new_status="approved", actor_id="bob", note="looks good"
        )
        db_session.commit()

        assert updated.status == "approved"
        assert updated.reviewed_by == "bob"
        assert updated.reviewed_at is not None

    def test_reject_sample(self, db_session: Session):
        h, m, e = self._setup(db_session)
        sample = create_hard_sample(
            db_session, household_id=h.id, member_id=m.id,
            source_event_id=e.id, category="hard_similar", created_by="alice",
        )
        db_session.commit()

        updated = update_hard_sample_status(
            db_session, sample, new_status="rejected", actor_id="bob"
        )
        db_session.commit()
        assert updated.status == "rejected"

    def test_cannot_approve_non_pending(self, db_session: Session):
        h, m, e = self._setup(db_session)
        sample = create_hard_sample(
            db_session, household_id=h.id, member_id=m.id,
            source_event_id=e.id, category="hard_foreign", created_by="alice",
        )
        db_session.commit()
        update_hard_sample_status(db_session, sample, new_status="approved", actor_id="bob")
        db_session.commit()

        with pytest.raises(ValueError, match="SAMPLE_NOT_PENDING"):
            update_hard_sample_status(db_session, sample, new_status="rejected", actor_id="bob")

    def test_soft_delete_cascades_consent_and_manifest(self, db_session: Session):
        h, m, e = self._setup(db_session)
        sample = create_hard_sample(
            db_session, household_id=h.id, member_id=m.id,
            source_event_id=e.id, category="hard_font", created_by="alice",
        )
        db_session.commit()
        # Approve and grant consent
        update_hard_sample_status(db_session, sample, new_status="approved", actor_id="bob")
        db_session.commit()
        consent = grant_training_consent(
            db_session, hard_sample_id=sample.id, household_id=h.id,
            member_id=m.id, granted_by="alice",
        )
        db_session.commit()
        # Create a manifest with this sample
        manifest = create_export_manifest(
            db_session, household_id=h.id, version="delete-test-v1",
            group_key="g1", license="internal", sample_ids=[sample.id],
            created_by="alice",
        )
        db_session.commit()

        # Delete the sample
        delete_hard_sample(db_session, sample, actor_id="alice")
        db_session.commit()

        # Verify cascades
        reloaded = get_hard_sample(db_session, sample.id)
        assert reloaded.status == "deleted"
        assert reloaded.deleted_by == "alice"

        # Consent should be revoked
        c = get_training_consent(db_session, sample.id)
        assert c is None  # no active consent

        # Manifest should be invalidated
        m2 = get_export_manifest(db_session, manifest.id)
        assert m2.status == "invalidated"

    def test_list_excludes_deleted_by_default(self, db_session: Session):
        h, m, e = self._setup(db_session)
        s1 = create_hard_sample(
            db_session, household_id=h.id, member_id=m.id,
            source_event_id=e.id, category="hard_font", created_by="alice",
        )
        db_session.commit()
        delete_hard_sample(db_session, s1, actor_id="alice")
        db_session.commit()

        results = list_hard_samples(db_session, h.id)
        assert len(results) == 0

        results_with_deleted = list_hard_samples(db_session, h.id, include_deleted=True)
        assert len(results_with_deleted) == 1


class TestTrainingConsent:
    def _setup_approved(self, db_session: Session) -> tuple[Household, Member, str]:
        """Return household, member, and approved sample_id."""
        household = Household(name="Test", created_by="alice")
        db_session.add(household)
        db_session.flush()
        member = Member(household_id=household.id, display_name="M1", role="DEPENDENT")
        db_session.add(member)
        db_session.flush()
        event = HealthEvent(
            household_id=household.id, member_id=member.id, sequence_no=1,
            event_type="test", source="MANUAL", confirmation_status="CONFIRMED",
            payload={}, evidence={}, created_by="alice", correlation_id="c1",
        )
        db_session.add(event)
        db_session.commit()
        sample = create_hard_sample(
            db_session, household_id=household.id, member_id=member.id,
            source_event_id=event.id, category="hard_font", created_by="alice",
        )
        db_session.commit()
        update_hard_sample_status(db_session, sample, new_status="approved", actor_id="bob")
        db_session.commit()
        return household, member, sample.id

    def test_grant_consent_requires_approved(self, db_session: Session):
        h, m, e = self._setup_with_event(db_session)
        sample = create_hard_sample(
            db_session, household_id=h.id, member_id=m.id,
            source_event_id=e.id, category="hard_layout", created_by="alice",
        )
        db_session.commit()
        # Still pending
        with pytest.raises(ValueError, match="SAMPLE_NOT_APPROVED"):
            grant_training_consent(
                db_session, hard_sample_id=sample.id, household_id=h.id,
                member_id=m.id, granted_by="alice",
            )

    def _setup_with_event(self, db_session: Session) -> tuple[Household, Member, HealthEvent]:
        household = Household(name="Test", created_by="alice")
        db_session.add(household)
        db_session.flush()
        member = Member(household_id=household.id, display_name="M1", role="DEPENDENT")
        db_session.add(member)
        db_session.flush()
        event = HealthEvent(
            household_id=household.id, member_id=member.id, sequence_no=1,
            event_type="test", source="MANUAL", confirmation_status="CONFIRMED",
            payload={}, evidence={}, created_by="alice", correlation_id="c1",
        )
        db_session.add(event)
        db_session.commit()
        return household, member, event

    def test_grant_and_revoke_consent(self, db_session: Session):
        h, m, sample_id = self._setup_approved(db_session)

        consent = grant_training_consent(
            db_session, hard_sample_id=sample_id, household_id=h.id,
            member_id=m.id, granted_by="alice", scope={"purpose": "train"},
            license="CC BY 4.0",
        )
        db_session.commit()
        assert consent.status == "active"
        assert consent.scope == {"purpose": "train"}

        # Revoke
        revoked = revoke_training_consent(
            db_session, sample_id, actor_id="alice", reason="no longer needed"
        )
        db_session.commit()
        assert revoked.status == "revoked"
        assert revoked.revoked_by == "alice"

        # No active consent
        assert get_training_consent(db_session, sample_id) is None

    def test_grant_replaces_active_consent(self, db_session: Session):
        h, m, sample_id = self._setup_approved(db_session)
        c1 = grant_training_consent(
            db_session, hard_sample_id=sample_id, household_id=h.id,
            member_id=m.id, granted_by="alice",
        )
        db_session.commit()
        c2 = grant_training_consent(
            db_session, hard_sample_id=sample_id, household_id=h.id,
            member_id=m.id, granted_by="alice",
        )
        db_session.commit()

        assert c1.id != c2.id
        assert c2.status == "active"
        # c1 should be revoked
        db_session.refresh(c1)
        assert c1.status == "revoked"

    def test_revoke_nonexistent_raises(self, db_session: Session):
        with pytest.raises(ValueError, match="NO_ACTIVE_CONSENT"):
            revoke_training_consent(db_session, "nonexistent", actor_id="alice")


class TestExportManifest:
    def _setup_with_consent(self, db_session: Session) -> tuple[Household, Member, str]:
        household = Household(name="Test", created_by="alice")
        db_session.add(household)
        db_session.flush()
        member = Member(household_id=household.id, display_name="M1", role="DEPENDENT")
        db_session.add(member)
        db_session.flush()
        event = HealthEvent(
            household_id=household.id, member_id=member.id, sequence_no=1,
            event_type="test", source="MANUAL", confirmation_status="CONFIRMED",
            payload={"drug": "test"}, evidence={}, created_by="alice", correlation_id="c1",
        )
        db_session.add(event)
        db_session.commit()
        sample = create_hard_sample(
            db_session, household_id=household.id, member_id=member.id,
            source_event_id=event.id, category="hard_condition", created_by="alice",
        )
        db_session.commit()
        update_hard_sample_status(db_session, sample, new_status="approved", actor_id="bob")
        db_session.commit()
        grant_training_consent(
            db_session, hard_sample_id=sample.id, household_id=household.id,
            member_id=member.id, granted_by="alice",
        )
        db_session.commit()
        return household, member, sample.id

    def test_create_manifest(self, db_session: Session):
        h, m, sample_id = self._setup_with_consent(db_session)
        manifest = create_export_manifest(
            db_session, household_id=h.id, version="test-v1",
            group_key="box_001", license="internal", sample_ids=[sample_id],
            created_by="alice",
        )
        db_session.commit()
        assert manifest.status == "active"
        assert manifest.total_samples == 1
        assert manifest.content_hash is not None
        assert len(manifest.event_ids) == 1

    def test_manifest_rejects_sample_without_consent(self, db_session: Session):
        h, m, sample_id = self._setup_with_consent(db_session)
        # Create another sample without consent
        event = HealthEvent(
            household_id=h.id, member_id=m.id, sequence_no=2,
            event_type="test2", source="MANUAL", confirmation_status="CONFIRMED",
            payload={}, evidence={}, created_by="alice", correlation_id="c2",
        )
        db_session.add(event)
        db_session.commit()
        s2 = create_hard_sample(
            db_session, household_id=h.id, member_id=m.id,
            source_event_id=event.id, category="hard_font", created_by="alice",
        )
        db_session.commit()
        update_hard_sample_status(db_session, s2, new_status="approved", actor_id="bob")
        db_session.commit()
        # No consent for s2

        with pytest.raises(ValueError, match="TRAINING_CONSENT_REQUIRED"):
            create_export_manifest(
                db_session, household_id=h.id, version="no-consent-v1",
                group_key="g1", license="internal", sample_ids=[sample_id, s2.id],
                created_by="alice",
            )

    def test_manifest_version_unique(self, db_session: Session):
        h, m, sample_id = self._setup_with_consent(db_session)
        create_export_manifest(
            db_session, household_id=h.id, version="dup-v1",
            group_key="g1", license="internal", sample_ids=[sample_id],
            created_by="alice",
        )
        db_session.commit()

        with pytest.raises(ValueError, match="VERSION_ALREADY_EXISTS"):
            create_export_manifest(
                db_session, household_id=h.id, version="dup-v1",
                group_key="g2", license="cc", sample_ids=[sample_id],
                created_by="alice",
            )

    def test_invalidate_manifest(self, db_session: Session):
        h, m, sample_id = self._setup_with_consent(db_session)
        manifest = create_export_manifest(
            db_session, household_id=h.id, version="inval-v1",
            group_key="g1", license="internal", sample_ids=[sample_id],
            created_by="alice",
        )
        db_session.commit()

        invalidate_export_manifest(db_session, manifest, actor_id="alice", reason="test")
        db_session.commit()

        reloaded = get_export_manifest(db_session, manifest.id)
        assert reloaded.status == "invalidated"
        assert reloaded.invalidated_by == "alice"

    def test_cannot_invalidate_non_active(self, db_session: Session):
        h, m, sample_id = self._setup_with_consent(db_session)
        manifest = create_export_manifest(
            db_session, household_id=h.id, version="inval-v2",
            group_key="g1", license="internal", sample_ids=[sample_id],
            created_by="alice",
        )
        db_session.commit()
        invalidate_export_manifest(db_session, manifest, actor_id="alice")
        db_session.commit()

        with pytest.raises(ValueError, match="MANIFEST_NOT_ACTIVE"):
            invalidate_export_manifest(db_session, manifest, actor_id="alice")

    def test_revoke_consent_invalidates_manifest(self, db_session: Session):
        h, m, sample_id = self._setup_with_consent(db_session)
        manifest = create_export_manifest(
            db_session, household_id=h.id, version="revoke-inval-v1",
            group_key="g1", license="internal", sample_ids=[sample_id],
            created_by="alice",
        )
        db_session.commit()

        revoke_training_consent(db_session, sample_id, actor_id="alice", reason="test cascade")
        db_session.commit()

        reloaded = get_export_manifest(db_session, manifest.id)
        assert reloaded.status == "invalidated"

    def test_cross_household_isolation(self, db_session: Session):
        h1, m1, sample_id = self._setup_with_consent(db_session)
        # Create household 2
        h2 = Household(name="H2", created_by="bob")
        db_session.add(h2)
        db_session.commit()

        # List hard samples for h2 should be empty
        results = list_hard_samples(db_session, h2.id)
        assert len(results) == 0

        # Export manifests for h2 should be empty
        manifests = list_export_manifests(db_session, h2.id)
        assert len(manifests) == 0
