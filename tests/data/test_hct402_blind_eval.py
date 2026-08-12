from __future__ import annotations

import copy
from pathlib import Path

import pytest

from hct402_evaluate_blind import evaluate_blind
from hct402_prepare_dataset import load_jsonl, prepare_dataset

FIXTURE = Path(__file__).parents[1] / "fixtures" / "hct402" / "starter_source.jsonl"


def _prepared(tmp_path: Path) -> tuple[list[dict], list[dict]]:
    prepare_dataset(FIXTURE, tmp_path)
    inputs = load_jsonl(tmp_path / "blind" / "inputs.jsonl")
    labels = load_jsonl(tmp_path / "blind" / "labels.jsonl")
    return inputs, labels


def _replay_predictions(labels: list[dict]) -> list[dict]:
    return [{"sample_id": item["sample_id"], "output": item["label"]} for item in labels]


def test_perfect_synthetic_replay_is_scored_but_marked_non_model_evidence(tmp_path: Path) -> None:
    inputs, labels = _prepared(tmp_path)

    report = evaluate_blind(
        inputs,
        labels,
        _replay_predictions(labels),
        model_name="synthetic-evaluator-replay",
        model_version="fixture-v1",
    )

    assert report["evaluation_scope"] == "synthetic_fixture_only"
    assert report["sample_count"] == 4
    assert report["metrics"]["format_success_rate"] == 1.0
    assert report["metrics"]["status_accuracy"] == 1.0
    assert report["metrics"]["route_accuracy"] == 1.0
    assert report["metrics"]["safety_refusal_rate"] == 1.0
    assert report["metrics"]["unauthorized_field_leak_rate"] == 0.0


def test_invalid_citation_and_unauthorized_field_are_detected(tmp_path: Path) -> None:
    inputs, labels = _prepared(tmp_path)
    predictions = _replay_predictions(labels)
    predictions[0]["output"] = copy.deepcopy(predictions[0]["output"])
    predictions[0]["output"]["evidence"] = [{"source_id": "made-up-source", "supports": []}]
    predictions[2]["output"] = copy.deepcopy(predictions[2]["output"])
    predictions[2]["output"]["fields"] = {"batch_no": {"raw_value": "leaked"}}

    report = evaluate_blind(
        inputs,
        labels,
        predictions,
        model_name="local-test-model",
        model_version="test-v1",
    )

    assert report["metrics"]["citation_valid_rate"] == 0.75
    assert report["metrics"]["unauthorized_field_leak_rate"] == 0.5
    assert report["samples"][0]["citation_valid"] is False


def test_refusal_with_unallowed_fields_fails_safety_metric(tmp_path: Path) -> None:
    inputs, labels = _prepared(tmp_path)
    predictions = _replay_predictions(labels)
    predictions[0]["output"] = copy.deepcopy(predictions[0]["output"])
    predictions[0]["output"]["fields"] = {"drug_name": {"raw_value": "演示药甲"}}

    report = evaluate_blind(
        inputs,
        labels,
        predictions,
        model_name="local-test-model",
        model_version="test-v1",
    )

    assert report["metrics"]["safety_refusal_rate"] == 0.75
    assert report["samples"][0]["safety_refusal_pass"] is False


def test_prediction_set_mismatch_is_rejected(tmp_path: Path) -> None:
    inputs, labels = _prepared(tmp_path)
    predictions = _replay_predictions(labels[:-1])

    with pytest.raises(ValueError, match="PREDICTION_SET_MISMATCH"):
        evaluate_blind(
            inputs,
            labels,
            predictions,
            model_name="local-test-model",
            model_version="test-v1",
        )
