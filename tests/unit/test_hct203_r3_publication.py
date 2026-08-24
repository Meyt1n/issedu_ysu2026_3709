from __future__ import annotations

from hct203_maintainer_waiver import evaluate_maintainer_waiver
from hct203_publish import prepare_publication
from hct203_r3_review import evaluate_r3_review
from hct203_release_gate import candidate_evaluation_from_registry, evaluate_release_readiness


def _ready_gate() -> dict:
    return {
        "passed": True,
        "decision": "READY_FOR_R3_REVIEW",
        "model_id": "hct-yolo11n-box-assist-v1.0",
        "fixed_set_hash": "d" * 64,
        "report_sha256": "e" * 64,
        "input_sha256": {"registry": "a" * 64},
    }


def _approved_review() -> dict:
    return {
        "schema_version": "hct203-r3-review/v1",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-08-24T12:00:00+08:00",
        "decision": "APPROVE_RELEASE",
        "scope_confirmed": True,
        "dataset_approval_confirmed": True,
        "independent_evaluation_confirmed": True,
        "hard_negative_confirmed": True,
        "rollback_confirmed": True,
        "runtime_scope_confirmed": True,
        "limitations_acknowledged": True,
        "machine_gate_report_sha256": "b" * 64,
        "report_sha256": "f" * 64,
    }


def test_r3_review_is_separate_from_machine_gate() -> None:
    report = evaluate_r3_review(_ready_gate(), _approved_review())

    assert report["decision"] == "R3_APPROVED"
    assert report["passed"] is True


def test_r3_review_does_not_approve_when_machine_gate_is_blocked() -> None:
    blocked = {**_ready_gate(), "passed": False, "decision": "BLOCK_MODEL_RELEASE"}
    report = evaluate_r3_review(blocked, _approved_review())

    assert report["decision"] == "R3_REVIEW_REQUIRED"
    assert report["passed"] is False


def test_publication_is_auxiliary_only_and_requires_r3_and_rollback() -> None:
    r3 = evaluate_r3_review(_ready_gate(), _approved_review())
    r3["input_sha256"] = {"machine_gate": "b" * 64}
    r3["report_sha256"] = "f" * 64
    publication = prepare_publication(
        registry={
            "model_id": "hct-yolo11n-box-assist-v1.0",
            "release_status": "EXPERIMENTAL_UNRELEASED",
            "training": {"dataset_version": "approved-v1"},
            "artifacts": {"weights_sha256": "c" * 64},
            "evaluation": {"test_set_sha256": "d" * 64},
        },
        machine_gate=_ready_gate(),
        r3_review={**r3, "input_sha256": {"machine_gate": "b" * 64}},
        rollback={"previous_version": "hct-yolo-v0", "restore_verified": True},
    )

    assert publication["decision"] == "MODEL_PUBLISHED"
    assert publication["publication_status"] == "PUBLISHED_AUXILIARY_ONLY"
    assert publication["runtime_scope"]["enabled_by_default"] is False


def test_maintainer_waiver_allows_candidate_only_publication_scope() -> None:
    waiver = evaluate_maintainer_waiver(
        {
            "schema_version": "hct203-maintainer-waiver/v1",
            "model_id": "hct-yolo11n-box-assist-v1.0",
            "approved": True,
            "approved_by": "current-maintainer",
            "approved_at": "2026-08-24",
            "waived_requirements": [
                "approved_real_fixed_set",
                "external_weights_verification",
                "independent_r3_record",
            ],
            "risk_acknowledged": True,
            "runtime_scope": "AUXILIARY_ONLY",
            "hard_negative_disclosure": "VISIBLE",
            "rollback_required": True,
        },
        registry={
            "model_id": "hct-yolo11n-box-assist-v1.0",
            "release_status": "EXPERIMENTAL_UNRELEASED",
            "artifacts": {"weights_sha256": "c" * 64},
        },
        rollback={"rollback_tested": True, "restore_verified": True},
    )

    assert waiver["decision"] == "MAINTAINER_WAIVER_APPROVED"


def test_release_gate_accepts_only_explicit_candidate_waiver_mode() -> None:
    registry = {
        "model_id": "hct-yolo11n-box-assist-v1.0",
        "release_status": "EXPERIMENTAL_UNRELEASED",
        "training": {
            "dataset_status": "QUARANTINED_UNRELEASED",
            "dataset_manifest_sha256": "a" * 64,
        },
        "artifacts": {
            "weights_sha256": "b" * 64,
            "evaluation_report_sha256": "c" * 64,
            "threshold_report_sha256": "d" * 64,
        },
        "evaluation": {
            "test": {
                "precision": 0.98,
                "recall": 1.0,
                "map50": 0.99,
                "map50_95": 0.92,
            },
            "hard_negatives": [{"sample_id": "hard-1", "false_positive": True}],
            "performance": {"input_set_sha256": "e" * 64},
        },
    }
    report = evaluate_release_readiness(
        model_kind="yolo",
        registry=registry,
        dataset_gate={},
        evaluation=candidate_evaluation_from_registry(registry),
        rollback={"rollback_tested": True, "previous_version": "v0", "restore_verified": True},
        waiver={"passed": True, "decision": "MAINTAINER_WAIVER_APPROVED"},
    )

    assert report["passed"] is True
    assert report["decision"] == "READY_FOR_MAINTAINER_WAIVER_PUBLICATION"
    assert report["release_mode"] == "MAINTAINER_WAIVER"
