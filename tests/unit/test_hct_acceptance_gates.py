from __future__ import annotations

import hashlib
import json

from hct201_fixed_set_gate import evaluate_fixed_set
from hct203_release_gate import evaluate_release_readiness
from hct205_accuracy_report import evaluate_records
from hct205_master_data_gate import gate_snapshot
from hct302_acceptance_report import evaluate_cases
from hct305_provider_preflight import preflight
from hct308_acceptance_report import evaluate_trace
from hct403_assistant_acceptance_gate import evaluate_assistant_evidence
from hct405_acceptance_gate import evaluate as evaluate_hct405
from hct409_release_gate import evaluate as evaluate_hct409


def test_fixed_set_requires_12_to_20_drugs_and_unknown_conflict() -> None:
    records = [
        {
            "sample_id": f"known-{index}",
            "status": "APPROVED",
            "dataset_scope": "approved_real_fixed_set",
            "dataset_version": "fixed-v1",
            "dataset_approval_ref": "review/approved",
            "review_record_ref": "review/fixed",
            "case_type": "known",
            "drug_id": f"drug-{index}",
            "split": "test",
            "fixed_eval": True,
        }
        for index in range(12)
    ]
    records += [
        {
            "sample_id": "unknown-1",
            "status": "APPROVED",
            "dataset_scope": "approved_real_fixed_set",
            "dataset_version": "fixed-v1",
            "dataset_approval_ref": "review/approved",
            "review_record_ref": "review/fixed",
            "case_type": "unknown",
            "split": "unknown",
            "fixed_eval": True,
            "unknown_set": True,
            "unknown_reason": "not in master data",
        },
        {
            "sample_id": "conflict-1",
            "status": "APPROVED",
            "dataset_scope": "approved_real_fixed_set",
            "dataset_version": "fixed-v1",
            "dataset_approval_ref": "review/approved",
            "review_record_ref": "review/fixed",
            "case_type": "conflict",
            "split": "test",
            "fixed_eval": True,
            "expected_status": "CONFLICT",
            "conflict_reason": "OCR and barcode disagree",
        },
    ]
    assert evaluate_fixed_set(records) == []


def test_accuracy_report_allows_real_scope_only() -> None:
    records = [
        {
            "sample_id": "real-1",
            "dataset_status": "APPROVED",
            "dataset_scope": "approved_real_fixed_set",
            "channel": "ocr",
            "expected_status": "MATCHED",
            "predicted_status": "MATCHED",
            "confidence": 0.99,
            "threshold_version": "threshold-v1",
            "source_ref": "review/sample-1",
            "expected": {"drug_name": "布洛芬", "specification": "0.3克"},
            "predicted": {"drug_name": " 布洛芬 ", "specification": "0.3克"},
        },
        {
            "sample_id": "real-2",
            "dataset_status": "APPROVED",
            "dataset_scope": "approved_real_fixed_set",
            "channel": "barcode",
            "expected_status": "CONFLICT",
            "predicted_status": "CONFLICT",
            "confidence": 0.91,
            "threshold_version": "threshold-v1",
            "source_ref": "review/sample-2",
            "expected": {"barcode": "690000000001"},
            "predicted": {"barcode": "690000000001"},
        },
    ]
    report = evaluate_records(
        records,
        threshold_version="threshold-v1",
        min_field_accuracy=1.0,
        min_barcode_accuracy=1.0,
        min_status_accuracy=1.0,
        require_formal_evidence=False,
    )
    assert report["decision"] == "ACCEPT_OCR_BARCODE_MASTER_DATA"
    assert report["metrics"]["status_accuracy"] == 1.0


def test_accuracy_report_does_not_accept_synthetic_fixture() -> None:
    row = {
        "sample_id": "synthetic-1",
        "dataset_status": "APPROVED",
        "dataset_scope": "synthetic_fixture_only",
        "channel": "ocr",
        "expected_status": "MATCHED",
        "predicted_status": "MATCHED",
        "confidence": 0.99,
        "threshold_version": "threshold-v1",
        "source_ref": "fixture/1",
        "expected": {"drug_name": "演示药"},
        "predicted": {"drug_name": "演示药"},
    }
    report = evaluate_records(
        [row], threshold_version="threshold-v1", allow_synthetic=True, min_barcode_accuracy=0
    )
    assert report["passed"] is False
    assert report["decision"] == "BLOCK_OCR_BARCODE_MASTER_DATA"


def test_hct205_formal_report_requires_approved_evidence_and_exports_safe_failures() -> None:
    fixed = [
        {
            "sample_id": f"known-{index}",
            "status": "APPROVED",
            "dataset_scope": "approved_real_fixed_set",
            "dataset_version": "fixed-v1",
            "dataset_approval_ref": "review/approved",
            "review_record_ref": "review/fixed",
            "case_type": "known",
            "drug_id": f"drug-{index}",
            "split": "test",
            "fixed_eval": True,
        }
        for index in range(12)
    ]
    fixed += [
        {
            "sample_id": "unknown-1",
            "status": "APPROVED",
            "dataset_scope": "approved_real_fixed_set",
            "dataset_version": "fixed-v1",
            "dataset_approval_ref": "review/approved",
            "review_record_ref": "review/fixed",
            "case_type": "unknown",
            "split": "unknown",
            "fixed_eval": True,
            "unknown_set": True,
            "unknown_reason": "not in master",
        },
        {
            "sample_id": "conflict-1",
            "status": "APPROVED",
            "dataset_scope": "approved_real_fixed_set",
            "dataset_version": "fixed-v1",
            "dataset_approval_ref": "review/approved",
            "review_record_ref": "review/fixed",
            "case_type": "conflict",
            "split": "test",
            "fixed_eval": True,
            "expected_status": "CONFLICT",
            "conflict_reason": "evidence conflict",
        },
    ]
    master_gate = {
        "schema_version": "hct205-approved-master-data-gate/v1",
        "passed": True,
        "decision": "ALLOW_APPROVED_MASTER_DATA",
        "version": "master-v1",
        "master_data_sha256": "a" * 64,
        "snapshot_file_sha256": "c" * 64,
        "record_ids": [f"drug-{index}" for index in range(12)],
        "fixed_set_manifest_sha256": "b" * 64,
    }
    results = []
    for row in fixed:
        expected_status = {"known": "MATCHED", "unknown": "UNKNOWN", "conflict": "CONFLICT"}[
            row["case_type"]
        ]
        value = (
            {"drug_name": "controlled"}
            if row["case_type"] == "known"
            else {"barcode": "controlled"}
        )
        result = {
            "sample_id": row["sample_id"],
            "dataset_status": "APPROVED",
            "dataset_scope": "approved_real_fixed_set",
            "dataset_version": "fixed-v1",
            "master_data_version": "master-v1",
            "master_data_sha256": "a" * 64,
            "master_data_record_id": row.get("drug_id"),
            "channel": "ocr",
            "expected_status": expected_status,
            "predicted_status": expected_status,
            "confidence": 0.99,
            "threshold_version": "threshold-v1",
            "source_ref": f"review/{row['sample_id']}",
            "expected": value,
            "predicted": dict(value),
        }
        results.append(result)
    results[0]["predicted"] = {"drug_name": "wrong"}

    report = evaluate_records(
        results,
        threshold_version="threshold-v1",
        min_field_accuracy=1.0,
        min_barcode_accuracy=0.0,
        min_status_accuracy=1.0,
        fixed_set_records=fixed,
        fixed_set_manifest_sha256="b" * 64,
        master_data_gate=master_gate,
    )
    assert report["passed"] is False
    assert report["metrics"]["failure_count"] == 1
    failure = report["failure_samples"][0]
    assert "FIELD_MISMATCH:drug_name" in failure["failure_codes"]
    assert "expected" not in failure and "predicted" not in failure


def test_hct205_master_data_gate_blocks_demo_sized_snapshot(tmp_path) -> None:
    document = {
        "schema_version": "hct-master-data/v1",
        "version": "demo-master-v1",
        "approval_status": "APPROVED",
        "approval_ref": "review/demo",
        "revocation_status": "ACTIVE",
        "records": [
            {
                "record_id": "demo-1",
                "name_aliases": ["演示药"],
                "specification": "demo",
                "manufacturer": "demo",
            },
            {
                "record_id": "demo-2",
                "name_aliases": ["演示药二"],
                "specification": "demo",
                "manufacturer": "demo",
            },
        ],
    }
    canonical = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    document["sha256"] = hashlib.sha256(canonical).hexdigest()
    path = tmp_path / "demo-master-v1.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    report = gate_snapshot(path)
    assert report["passed"] is False
    assert report["decision"] == "BLOCK_APPROVED_MASTER_DATA"
    assert any(item["code"] == "RECORD_COUNT_OUT_OF_RANGE" for item in report["findings"])


def test_rules_require_provenance_and_cover_duplicate_and_interaction() -> None:
    common = {
        "case_status": "APPROVED",
        "data_scope": "synthetic_fixture_only",
        "rule_version": "rules-v1",
        "master_data_version": "master-v1",
        "source_ref": "fixture/rules",
    }
    cases = [
        {
            **common,
            "case_id": "duplicate",
            "rule_id": "duplicate_ingredient",
            "expected_level": "WARNING",
            "expected_source_event_ids": ["event-a", "event-b"],
            "facts": {
                "drugs": [
                    {"active_ingredients": ["成分甲"], "added_by": "event-a"},
                    {"active_ingredients": ["成分甲"], "added_by": "event-b"},
                ]
            },
        },
        {
            **common,
            "case_id": "interaction",
            "rule_id": "interaction",
            "expected_level": "WARNING",
            "expected_source_event_ids": ["event-a", "event-b"],
            "facts": {
                "drugs": [
                    {
                        "candidate_id": "a",
                        "added_by": "event-a",
                        "interaction_warnings": [{"with_record_id": "b", "level": "WARNING"}],
                    },
                    {"candidate_id": "b", "added_by": "event-b"},
                ]
            },
        },
    ]
    report = evaluate_cases(cases, allow_synthetic=True)
    assert report["passed"] is True


def test_reminder_trace_requires_all_six_scenarios() -> None:
    trace = {
        "execution_scope": "approved_local_api",
        "scenarios": [
            {
                "scenario_id": scenario_id,
                "result": "PASS",
                "evidence_ref": f"evidence/{scenario_id}",
                "event_types": [
                    {
                        "confirm": "plan_confirmed",
                        "defer": "plan_deferred",
                        "missed": "plan_missed",
                        "course_end": "plan_completed",
                        "escalation": "care_escalated",
                        "caregiver_escalation": "caregiver_notified",
                    }[scenario_id]
                ],
                "assertions": ["event and idempotency verified"],
                "caregiver_notification": scenario_id == "caregiver_escalation",
            }
            for scenario_id in (
                "confirm",
                "defer",
                "missed",
                "course_end",
                "escalation",
                "caregiver_escalation",
            )
        ],
    }
    assert evaluate_trace(trace)["decision"] == "ACCEPT_REMINDER_FLOW"


def test_assistant_gate_requires_real_hash_and_degradation() -> None:
    blind = {
        "evaluation_scope": "model_prediction_file",
        "model": {"name": "hct402", "version": "v1", "sha256": "a" * 64},
        "metrics": {
            "citation_valid_rate": 1.0,
            "unauthorized_field_leak_rate": 0,
            "safety_refusal_rate": 1.0,
        },
    }
    red_team = {
        "scenarios": [
            {
                "scenario_id": scenario_id,
                "result": "PASS",
                "evidence_ref": f"evidence/{scenario_id}",
            }
            for scenario_id in (
                "medical_refusal",
                "prompt_injection",
                "cross_member",
                "missing_evidence",
            )
        ]
    }
    degradation = {
        "execution_scope": "approved_local_api",
        "ollama_disconnect": {"result": "PASS", "evidence_ref": "evidence/ollama-offline"},
    }
    assert (
        evaluate_assistant_evidence(blind=blind, red_team=red_team, degradation=degradation)[
            "passed"
        ]
        is True
    )


def test_weather_preflight_is_fail_closed() -> None:
    report = preflight(
        provider="uapis",
        url="https://weather.example.test/api",
        city_code="130600",
        district_code="130629",
        allowed_hosts={"weather.example.test"},
    )
    assert report["decision"] == "READY_FOR_LIVE_PROVIDER"
    blocked = preflight(
        provider="uapis",
        url="http://weather.example.test/api",
        city_code="130600",
        district_code="130629",
        allowed_hosts={"weather.example.test"},
    )
    assert blocked["passed"] is False


def test_hct405_and_hct409_require_release_only_evidence() -> None:
    scenarios = [
        {"scenario_id": scenario_id, "result": "PASS", "evidence_ref": f"evidence/{scenario_id}"}
        for scenario_id in (
            "family_login_to_member_context",
            "vision_scan_to_manual_confirm",
            "confirmed_event_to_rule_alert",
            "assistant_evidence_explanation",
            "offline_restart_degradation",
        )
    ]
    hct405 = evaluate_hct405(
        {
            "scenarios": scenarios,
            "deployment_drill": {"restart_verified": True, "offline_degradation_verified": True},
            "released_model_fixed_set_verified": True,
            "cross_team_r3_review": True,
        }
    )
    assert hct405["decision"] == "ACCEPT_CORE_E2E"
    hct409 = evaluate_hct409(
        {
            "api_perf": {
                "health_p95_ms": 20,
                "db_p95_ms": 30,
                "household_list_p95_ms": 50,
                "vision_full_pipeline_p95_ms": 7000,
                "error_rate": 0,
            },
            "security_regression_passed": True,
            "privacy_delete_propagation_passed": True,
            "red_team_passed": True,
            "dependency_audit_passed": True,
            "manual_screen_reader_passed": True,
            "project_lead_signoff": True,
            "independent_r3_review": True,
        }
    )
    assert hct409["decision"] == "READY_FOR_R3_REVIEW"


def test_model_release_gate_never_publishes_directly() -> None:
    evaluation = {
        "evaluation_scope": "approved_real_fixed_set",
        "independent_evaluation": True,
        "hard_negative_reviewed": True,
        "metrics": {"map50": 0.99},
        "evaluation_report_sha256": "b" * 64,
        "threshold_report_sha256": "c" * 64,
    }
    report = evaluate_release_readiness(
        model_kind="yolo",
        registry={
            "model_id": "model-v1",
            "release_status": "EXPERIMENTAL_UNRELEASED",
            "training": {"dataset_status": "APPROVED"},
        },
        dataset_gate={"passed": True, "decision": "ALLOW_APPROVED_FIXED_SET"},
        evaluation=evaluation,
        rollback={
            "rollback_tested": True,
            "previous_version": "model-v0",
            "restore_verified": True,
        },
    )
    assert report["decision"] == "READY_FOR_R3_REVIEW"
