from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).parents[2] / "scripts" / "hct201_formal_gate.py"
_SPEC = importlib.util.spec_from_file_location("hct201_formal_gate", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
evaluate = _MODULE.evaluate
load_manifest = _MODULE.load_manifest


def _record(sample_id: str, split: str, group: str) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "source_id": "synthetic-hct201-fixture",
        "source_url": "https://example.invalid/hct201-fixture",
        "license": "synthetic-no-third-party-rights",
        "consent_status": "synthetic",
        "authorization_evidence_ref": "fixture-generator-v1",
        "deidentified": True,
        "delete_ref": "fixture-output-delete-v1",
        "retention_until": "2026-12-31",
        "sha256": f"{sample_id:0<64}",
        "group_key": group,
        "entity_key": f"entity-{group}",
        "session_key": f"session-{group}",
        "grouping_evidence_ref": "fixture-generator-v1-seed-42",
        "split": split,
        "fixed_eval": split in {"test", "unknown"},
        "unknown_set": split == "unknown",
        "unknown_reason": "synthetic non-target" if split == "unknown" else None,
        "status": "APPROVED",
    }


def _valid_records() -> list[dict[str, object]]:
    return [
        _record("a", "train", "group-a"),
        _record("b", "validation", "group-b"),
        _record("c", "test", "group-c"),
        _record("d", "unknown", "group-d"),
    ]


def test_approved_manifest_with_frozen_test_and_unknown_passes() -> None:
    assert evaluate(_valid_records()) == []


def test_quarantined_proxy_group_is_blocked() -> None:
    record = _record("a", "train", "proxy-phash2-a")
    record["status"] = "QUARANTINED"
    record["grouping_evidence_ref"] = ""
    findings = evaluate([record, *_valid_records()[1:]])
    codes = {finding.code for finding in findings}
    assert {"DATA_NOT_APPROVED", "NOT_REAL_GROUP", "MISSING_GROUPING_EVIDENCE"} <= codes


def test_group_leak_and_unfrozen_unknown_are_blocked() -> None:
    records = _valid_records()
    records[2]["group_key"] = "group-b"
    records[3]["fixed_eval"] = False
    findings = evaluate(records)
    codes = {finding.code for finding in findings}
    assert {"GROUP_SPLIT_LEAK", "EVAL_NOT_FROZEN"} <= codes


def test_unknown_entity_or_session_keys_are_not_real_groups() -> None:
    records = _valid_records()
    records[0]["entity_key"] = "proxy-phash2-a"
    records[0]["session_key"] = "roboflow-v2-unknown"
    codes = {finding.code for finding in evaluate(records)}
    assert "MISSING_CAPTURE_GROUP" in codes


def test_current_style_manifest_is_not_accepted(tmp_path: Path) -> None:
    path = tmp_path / "candidate.jsonl"
    path.write_text(
        json.dumps({"status": "QUARANTINED", "split": "quarantine"}) + "\n", encoding="utf-8"
    )
    records = load_manifest(path)
    assert any(finding.code == "MISSING_METADATA" for finding in evaluate(records))


@pytest.mark.parametrize("split", ["train", "validation", "test", "unknown"])
def test_unknown_flag_must_match_split(split: str) -> None:
    record = _record("x", split, "group-x")
    record["unknown_set"] = split != "unknown"
    records = [record, *_valid_records()]
    assert any(finding.code == "UNKNOWN_FLAG_MISMATCH" for finding in evaluate(records))
