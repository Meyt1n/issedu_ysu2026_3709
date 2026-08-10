from __future__ import annotations

import copy
import json
from pathlib import Path

from hct203_model_registry_audit import audit_registry, load_registry, verify_weights


def valid_registry() -> dict:
    return {
        "schema_version": "hct-model-registry/v1",
        "model_id": "hct-yolo11n-box-assist-experimental-v1.2",
        "story": "HCT-203-D1",
        "issue": 112,
        "release_status": "EXPERIMENTAL_UNRELEASED",
        "task": "medicine_box_region_proposal",
        "training": {
            "dataset_version": "HCT-201-dataset-v1.2-annotation-reviewed-candidate",
            "dataset_manifest_sha256": "a" * 64,
            "configuration_sha256": "b" * 64,
            "random_seed": 42,
            "hardware": {"gpu": "RTX 4060 Laptop GPU"},
            "dependencies": {"ultralytics": "8.3.225", "torch": "2.7.1+cu118"},
            "reproducibility_status": "PARTIAL_UNTRACKED_ORIGINAL_CODE",
        },
        "artifacts": {
            "weights_sha256": "c" * 64,
            "weights_size_bytes": 5_499_089,
            "stored_outside_git": True,
            "evaluation_report_sha256": "d" * 64,
            "threshold_report_sha256": "e" * 64,
        },
        "evaluation": {
            "test": {
                "images": 147,
                "ground_truth_instances": 145,
                "precision": 0.986,
                "recall": 1.0,
                "map50": 0.995,
                "map50_95": 0.927,
                "confidence": 0.25,
            },
            "expected_hard_negative_sample_ids": ["hard-negative-1", "hard-negative-2"],
            "hard_negatives": [
                {"sample_id": "hard-negative-1", "false_positive": True, "confidence": 0.88},
                {"sample_id": "hard-negative-2", "false_positive": True, "confidence": 0.76},
            ],
        },
        "intended_uses": ["propose OCR crop regions"],
        "prohibited_uses": ["identify medicine"],
        "release_blockers": ["dataset is not approved"],
        "fallback": "vision_model_version=unavailable",
    }


def codes(record: dict) -> set[str]:
    return {finding.code for finding in audit_registry(record)}


def test_accepts_complete_unreleased_registry() -> None:
    assert audit_registry(valid_registry()) == []


def test_rejects_release_claim_invalid_hash_and_local_path() -> None:
    record = valid_registry()
    record["release_status"] = "RELEASED"
    record["artifacts"]["weights_sha256"] = "not-a-hash"
    record["artifacts"]["location"] = r"C:\training\best.pt"

    assert {
        "FORBIDDEN_RELEASE_STATUS",
        "INVALID_SHA256",
        "LOCAL_PATH_LEAK",
    } <= codes(record)


def test_rejects_posix_and_file_uri_paths() -> None:
    record = valid_registry()
    record["artifacts"]["posix_location"] = "/home/user/model.pt"
    record["artifacts"]["uri_location"] = "file:///Users/user/model.pt"

    findings = audit_registry(record)

    assert [finding.code for finding in findings].count("LOCAL_PATH_LEAK") == 2


def test_rejects_hidden_hard_negative_failure_and_missing_blockers() -> None:
    record = valid_registry()
    record["evaluation"]["hard_negatives"] = [
        {"sample_id": "hard-negative-1", "false_positive": False, "confidence": 0.88}
    ]
    record["release_blockers"] = []

    assert {
        "HARD_NEGATIVE_SET_MISMATCH",
        "HARD_NEGATIVE_FAILURE_HIDDEN",
        "MISSING_FIELD",
        "MISSING_RELEASE_BLOCKERS",
    } <= codes(record)


def test_rejects_misrepresented_original_reproducibility() -> None:
    record = valid_registry()
    record["training"]["reproducibility_status"] = "FULLY_REPRODUCIBLE"

    assert "MISSTATED_REPRODUCIBILITY" in codes(record)


def test_verifies_external_weights_content_and_rejects_mismatch(tmp_path: Path) -> None:
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"controlled synthetic weights fixture")
    record = valid_registry()

    import hashlib

    record["artifacts"]["weights_sha256"] = hashlib.sha256(weights.read_bytes()).hexdigest()
    assert verify_weights(record, weights) == []

    weights.write_bytes(b"tampered fixture")
    findings = verify_weights(record, weights)
    assert [finding.code for finding in findings] == ["WEIGHTS_HASH_MISMATCH"]


def test_repository_registry_passes() -> None:
    registry_path = (
        Path(__file__).parents[2]
        / "docs"
        / "model-registry"
        / "HCT-203-yolo11n-experimental-v1.2.json"
    )
    record = load_registry(registry_path)

    assert audit_registry(record) == []
    assert json.loads(json.dumps(copy.deepcopy(record))) == record
