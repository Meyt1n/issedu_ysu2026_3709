"""HCT-404: Model version binding, release management, and rollback.

Immutable ledger linking model_id → dataset_version → export_manifest → fixed_set_hash.
Only one binding can be active per model_id at a time.
"""

import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models import Base, new_id

logger = logging.getLogger(__name__)

# ── Default safety thresholds ────────────────────────────────────────────

DEFAULT_SAFETY_THRESHOLDS: dict[str, Any] = {
    "min_map50": 0.90,
    "min_map50_95": 0.85,
    "max_hard_negative_fp": 0,
    "require_comparison_report": True,
}
HCT203_MODEL_PREFIX = "hct-yolo"
HCT404_MODEL_PREFIX = "hct404-"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_hct203_publication(binding: "ModelVersionBinding") -> None:
    """Prevent an HCT-203 candidate from bypassing its publication manifest."""

    if not binding.model_id.startswith(HCT203_MODEL_PREFIX):
        return
    thresholds = binding.safety_thresholds or {}
    if thresholds.get("hct203_publication_status") != "PUBLISHED_AUXILIARY_ONLY":
        raise ValueError("HCT203_PUBLICATION_REQUIRED")
    authority = thresholds.get("hct203_release_authority")
    approval_field = (
        "hct203_waiver_sha256" if authority == "MAINTAINER_WAIVER" else "hct203_r3_review_sha256"
    )
    for field in ("hct203_machine_gate_sha256", approval_field):
        value = thresholds.get(field)
        if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
            raise ValueError(f"HCT203_PUBLICATION_HASH_REQUIRED:{field}")


def _requires_hct404_release_evidence(binding: "ModelVersionBinding") -> bool:
    thresholds = binding.safety_thresholds or {}
    return binding.model_id.startswith(HCT404_MODEL_PREFIX) or thresholds.get(
        "hct404_release_evidence_required"
    ) is True


def _validate_hct404_release_evidence(binding: "ModelVersionBinding") -> None:
    """Require a real HCT-404 release gate before formal model activation."""

    if not _requires_hct404_release_evidence(binding):
        return
    thresholds = binding.safety_thresholds or {}
    if thresholds.get("hct404_release_status") != "ALLOW_FORMAL_RELEASE":
        raise ValueError("HCT404_FORMAL_RELEASE_REQUIRED")
    if thresholds.get("hct404_release_evidence_schema") != "hct404-model-release-evidence/v1":
        raise ValueError("HCT404_RELEASE_EVIDENCE_SCHEMA_REQUIRED")
    required_hashes = {
        "release_evidence_hash": binding.release_evidence_hash,
        "hct404_release_evidence_sha256": thresholds.get("hct404_release_evidence_sha256"),
        "hct404_release_gate_sha256": thresholds.get("hct404_release_gate_sha256"),
        "hct404_model_artifact_sha256": thresholds.get("hct404_model_artifact_sha256"),
        "hct404_fixed_set_sha256": thresholds.get("hct404_fixed_set_sha256"),
        "hct404_comparison_report_sha256": thresholds.get("hct404_comparison_report_sha256"),
        "hct404_rollback_evidence_sha256": thresholds.get("hct404_rollback_evidence_sha256"),
        "hct404_approval_sha256": thresholds.get("hct404_approval_sha256"),
    }
    for field, value in required_hashes.items():
        if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
            raise ValueError(f"HCT404_RELEASE_EVIDENCE_HASH_REQUIRED:{field}")
    if binding.release_evidence_hash != thresholds.get("hct404_release_evidence_sha256"):
        raise ValueError("HCT404_RELEASE_EVIDENCE_HASH_MISMATCH")
    if binding.fixed_set_hash != thresholds.get("hct404_fixed_set_sha256"):
        raise ValueError("HCT404_FIXED_SET_HASH_MISMATCH")
    if binding.comparison_report_hash != thresholds.get("hct404_comparison_report_sha256"):
        raise ValueError("HCT404_COMPARISON_HASH_MISMATCH")


# ── Model ────────────────────────────────────────────────────────────────


class ModelVersionBinding(Base):
    """Immutable ledger entry linking a model ID to dataset version,
    export manifest, and fixed set hash.

    Lifecycle:
      inactive → active → revoked
    """

    __tablename__ = "model_version_binding"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    dataset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    export_manifest_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("export_manifest.id", ondelete="SET NULL"), nullable=True
    )
    fixed_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    release_status: Mapped[str] = mapped_column(String(32), nullable=False, default="inactive")
    safety_thresholds: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    comparison_report_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rollback_evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_model_binding_model_id", "model_id"),
        Index("ix_model_binding_release_status", "release_status"),
    )


# ── CRUD ──────────────────────────────────────────────────────────────────


def create_binding(
    session: Session,
    *,
    model_id: str,
    dataset_version: str,
    export_manifest_id: str | None,
    fixed_set_hash: str,
    safety_thresholds: dict[str, Any] | None = None,
    comparison_report_hash: str | None = None,
    release_evidence_hash: str | None = None,
    created_by: str,
) -> ModelVersionBinding:
    """Create a new model version binding (inactive)."""
    binding = ModelVersionBinding(
        model_id=model_id,
        dataset_version=dataset_version,
        export_manifest_id=export_manifest_id,
        fixed_set_hash=fixed_set_hash,
        release_status="inactive",
        safety_thresholds=safety_thresholds or DEFAULT_SAFETY_THRESHOLDS,
        comparison_report_hash=comparison_report_hash,
        release_evidence_hash=release_evidence_hash,
        created_by=created_by,
    )
    session.add(binding)
    session.flush()
    logger.info(
        "MODEL_BINDING_CREATED binding=%s model=%s dataset=%s actor=%s",
        binding.id, model_id, dataset_version, created_by,
    )
    return binding


def _deactivate_active_for_model(session: Session, model_id: str, actor_id: str) -> int:
    """Deactivate all active bindings for a model_id. Returns count deactivated."""
    active = list(session.scalars(
        select(ModelVersionBinding).where(
            ModelVersionBinding.model_id == model_id,
            ModelVersionBinding.release_status == "active",
        )
    ).all())
    for b in active:
        b.release_status = "inactive"
    if active:
        session.flush()
        logger.info(
            "MODEL_BINDING_DEACTIVATED model=%s count=%d actor=%s",
            model_id, len(active), actor_id,
        )
    return len(active)


def activate_binding(
    session: Session,
    binding: ModelVersionBinding,
    *,
    approved_by: str,
) -> ModelVersionBinding:
    """Activate a binding. Must be inactive. Deactivates any other active for same model_id.

    Requires comparison_report_hash to be set unless safety_thresholds explicitly
    disables require_comparison_report.
    """
    if binding.release_status == "revoked":
        raise ValueError("BINDING_ALREADY_REVOKED")
    if binding.release_status == "active":
        raise ValueError("BINDING_ALREADY_ACTIVE")

    _validate_hct203_publication(binding)
    _validate_hct404_release_evidence(binding)

    thresholds = binding.safety_thresholds or {}
    if thresholds.get("require_comparison_report", True) and not binding.comparison_report_hash:
        raise ValueError("COMPARISON_REPORT_REQUIRED")

    # Deactivate any currently active binding for this model_id
    _deactivate_active_for_model(session, binding.model_id, actor_id=approved_by)

    now = datetime.now(UTC)
    binding.release_status = "active"
    binding.approved_by = approved_by
    binding.approved_at = now
    session.flush()
    logger.info(
        "MODEL_BINDING_ACTIVATED binding=%s model=%s approved_by=%s",
        binding.id, binding.model_id, approved_by,
    )
    return binding


def rollback_binding(
    session: Session,
    binding: ModelVersionBinding,
    *,
    actor_id: str,
    reason: str = "",
    evidence_hash: str | None = None,
) -> ModelVersionBinding:
    """Revoke a binding. Tries to reactivate the chronologically previous binding.

    If no previous binding exists or it's also revoked, no active binding remains.
    """
    if binding.release_status != "active":
        raise ValueError("BINDING_NOT_ACTIVE")
    if _requires_hct404_release_evidence(binding):
        if not reason.strip():
            raise ValueError("HCT404_ROLLBACK_REASON_REQUIRED")
        if not isinstance(evidence_hash, str) or SHA256_RE.fullmatch(evidence_hash) is None:
            raise ValueError("HCT404_ROLLBACK_EVIDENCE_REQUIRED")

    now = datetime.now(UTC)
    binding.release_status = "revoked"
    binding.revoked_by = actor_id
    binding.revoked_at = now
    if evidence_hash is not None:
        binding.rollback_evidence_hash = evidence_hash
    session.flush()

    # Try to reactivate the previous binding for this model_id
    previous = session.scalars(
        select(ModelVersionBinding)
        .where(
            ModelVersionBinding.model_id == binding.model_id,
            ModelVersionBinding.id != binding.id,
            ModelVersionBinding.release_status == "inactive",
        )
        .order_by(ModelVersionBinding.created_at.desc())
    ).first()

    reactivated = None
    if previous is not None:
        _validate_hct203_publication(previous)
        _validate_hct404_release_evidence(previous)
        previous.release_status = "active"
        previous.approved_by = actor_id
        previous.approved_at = now
        reactivated = previous.id
        session.flush()

    logger.info(
        "MODEL_BINDING_ROLLBACK binding=%s model=%s reason=%s actor=%s reactivated=%s",
        binding.id, binding.model_id, reason, actor_id, reactivated,
    )
    return binding


def get_binding(session: Session, binding_id: str) -> ModelVersionBinding | None:
    return session.get(ModelVersionBinding, binding_id)


def get_active_binding(session: Session, model_id: str) -> ModelVersionBinding | None:
    """Get the currently active binding for a model_id, or None."""
    return session.scalar(
        select(ModelVersionBinding).where(
            ModelVersionBinding.model_id == model_id,
            ModelVersionBinding.release_status == "active",
        )
    )


def list_bindings(
    session: Session,
    *,
    model_id: str | None = None,
    release_status: str | None = None,
) -> list[ModelVersionBinding]:
    stmt = select(ModelVersionBinding)
    if model_id is not None:
        stmt = stmt.where(ModelVersionBinding.model_id == model_id)
    if release_status is not None:
        stmt = stmt.where(ModelVersionBinding.release_status == release_status)
    return list(session.scalars(stmt.order_by(ModelVersionBinding.created_at.desc())).all())


def resolve_active_model_version(session: Session) -> str | None:
    """Resolve the active model version for vision task creation.

    Returns the active binding's model_id if one exists (any model_id with active status),
    otherwise returns None (caller should fall back to config).
    """
    binding = session.scalars(
        select(ModelVersionBinding).where(
            ModelVersionBinding.release_status == "active",
        ).order_by(ModelVersionBinding.created_at.desc()).limit(1)
    ).first()
    if binding is None:
        return None
    return binding.model_id
