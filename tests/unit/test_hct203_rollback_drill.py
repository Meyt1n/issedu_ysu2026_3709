from __future__ import annotations

from hct203_rollback_drill import evaluate_rollback_drill


def test_rollback_drill_requires_candidate_revocation_and_previous_restore() -> None:
    report = evaluate_rollback_drill(
        before={
            "active_model_version": "hct-yolo-v2",
            "bindings": [
                {"model_id": "hct-yolo-v2", "release_status": "active"},
                {"model_id": "hct-yolo-v1", "release_status": "inactive"},
            ],
        },
        after={
            "active_model_version": "hct-yolo-v1",
            "bindings": [
                {"model_id": "hct-yolo-v2", "release_status": "revoked"},
                {"model_id": "hct-yolo-v1", "release_status": "active"},
            ],
        },
        current_version="hct-yolo-v2",
        previous_version="hct-yolo-v1",
        reason="synthetic rollback drill",
    )

    assert report["decision"] == "ROLLBACK_VERIFIED"
    assert report["restore_verified"] is True


def test_rollback_drill_blocks_wrong_active_version() -> None:
    report = evaluate_rollback_drill(
        before={"active_model_version": "hct-yolo-v2"},
        after={"active_model_version": "hct-yolo-v3"},
        current_version="hct-yolo-v2",
        previous_version="hct-yolo-v1",
        reason="synthetic rollback drill",
    )

    assert report["decision"] == "ROLLBACK_BLOCKED"
    assert report["restore_verified"] is False
