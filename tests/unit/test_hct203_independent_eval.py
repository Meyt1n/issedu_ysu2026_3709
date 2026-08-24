from __future__ import annotations

from hct203_independent_eval import (
    build_independent_evaluation_report,
    canonical_sha256,
    evaluate_metrics,
)

GOOD_METRICS = {
    "precision": 0.98,
    "recall": 0.97,
    "map50": 0.99,
    "map50_95": 0.90,
}


def test_independent_report_records_hashes_metrics_and_hard_negatives() -> None:
    report = build_independent_evaluation_report(
        weights_sha256="a" * 64,
        weights_size_bytes=123,
        dataset_yaml_sha256="b" * 64,
        test_set_sha256="c" * 64,
        test_images=24,
        metrics=GOOD_METRICS,
        hard_negatives=[
            {
                "sample_id": "synthetic-hard-negative-1",
                "prediction_count": 0,
                "max_confidence": 0.0,
                "false_positive": False,
            }
        ],
    )

    assert report["status"] == "PASSED"
    assert report["independent_evaluation"] is True
    assert report["hard_negative_reviewed"] is True
    assert report["evaluation_report_sha256"] == canonical_sha256(
        {key: value for key, value in report.items() if key != "evaluation_report_sha256"}
    )


def test_independent_report_blocks_hard_negative_false_positive() -> None:
    report = build_independent_evaluation_report(
        weights_sha256="a" * 64,
        weights_size_bytes=123,
        dataset_yaml_sha256="b" * 64,
        test_set_sha256="c" * 64,
        test_images=24,
        metrics=GOOD_METRICS,
        hard_negatives=[
            {
                "sample_id": "synthetic-hard-negative-1",
                "prediction_count": 1,
                "max_confidence": 0.81,
                "false_positive": True,
            }
        ],
    )

    assert report["status"] == "FAILED"
    assert any(item["code"] == "HARD_NEGATIVE_FALSE_POSITIVE" for item in report["findings"])


def test_independent_metrics_do_not_treat_missing_values_as_zero() -> None:
    findings = evaluate_metrics({"map50": 0.99})

    assert {item["code"] for item in findings} == {"METRIC_MISSING"}
