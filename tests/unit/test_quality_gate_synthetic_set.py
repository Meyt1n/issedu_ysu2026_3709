"""Regression tests for the synthetic quality-gate test set generator.

The generator replaces the studio-shot HCT-201 test images (which the
household gate rejects at 100% GLARE) for gate calibration and adapter
integration checks. Every variant must keep triggering exactly the gate
behaviour it was designed for.
"""

from __future__ import annotations

import json

from hct_quality_gate_synthetic_set import EXPECTATIONS, generate


def test_synthetic_set_meets_all_gate_expectations(tmp_path) -> None:
    manifest = generate(tmp_path, per_variant=2, seed=20260813)
    assert manifest["expectation_failures"] == []
    assert len(manifest["images"]) == 2 * len(EXPECTATIONS)

    by_variant = {}
    for record in manifest["images"]:
        by_variant.setdefault(record["variant"], []).append(record)

    for variant, expected in EXPECTATIONS.items():
        for record in by_variant[variant]:
            assert record["actual_decision"] == expected["decision"], record
            assert set(expected["reasons"]) <= set(record["actual_reasons"]), record

    # PASS variants exist so the adapter chain has usable local inputs.
    pass_records = [r for r in manifest["images"] if r["actual_decision"] == "PASS"]
    assert len(pass_records) == 4  # clean x2 + tilted x2


def test_synthetic_set_is_deterministic(tmp_path) -> None:
    first = generate(tmp_path / "a", per_variant=1, seed=7)
    second = generate(tmp_path / "b", per_variant=1, seed=7)
    hashes_a = [record["sha256"] for record in first["images"]]
    hashes_b = [record["sha256"] for record in second["images"]]
    assert hashes_a == hashes_b

    manifest_file = tmp_path / "a" / "manifest.json"
    stored = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert stored["schema_version"] == "hct-quality-gate-synthetic-set/v1"
