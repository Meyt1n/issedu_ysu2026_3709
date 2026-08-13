"""Contract checks for the twelve HCT-405 scenario definitions."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = Path(__file__).with_name("hct405_scenarios.json")
REQUIRED_LIST_FIELDS = {
    "preconditions",
    "roles",
    "steps",
    "expected_states",
    "audit_evidence",
    "coverage_tags",
    "automated_tests",
}
REQUIRED_COVERAGE_TAGS = {
    "matched",
    "conflict",
    "unknown",
    "low-quality",
    "manual-correction",
    "revocation",
    "no-evidence-refusal",
    "model-unavailable",
    "network-disconnect",
}
ALLOWED_STATUSES = {"automated", "automated_with_limitations"}


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_defines_exactly_twelve_unique_synthetic_scenarios() -> None:
    manifest = _manifest()
    scenarios = manifest["scenarios"]

    assert manifest["schema_version"] == "hct405-scenarios-v1"
    assert manifest["data_policy"] == "synthetic-only"
    assert len(scenarios) == 12
    assert [scenario["id"] for scenario in scenarios] == [
        f"HCT405-{index:02d}" for index in range(1, 13)
    ]


def test_each_scenario_has_roles_steps_boundaries_audit_and_cleanup() -> None:
    for scenario in _manifest()["scenarios"]:
        assert scenario["title"]
        assert scenario["status"] in ALLOWED_STATUSES
        assert scenario["permission_boundary"]
        assert scenario["cleanup"]
        assert isinstance(scenario["limitations"], list)
        for field in REQUIRED_LIST_FIELDS:
            assert isinstance(scenario[field], list), f"{scenario['id']}.{field}"
            assert scenario[field], f"{scenario['id']}.{field} must not be empty"


def test_manifest_covers_all_mandatory_failure_and_four_state_cases() -> None:
    covered = {
        tag
        for scenario in _manifest()["scenarios"]
        for tag in scenario["coverage_tags"]
    }

    assert REQUIRED_COVERAGE_TAGS <= covered


def test_all_automated_evidence_paths_exist_in_repository() -> None:
    for scenario in _manifest()["scenarios"]:
        for test_reference in scenario["automated_tests"]:
            relative_path = test_reference.split("::", maxsplit=1)[0]
            evidence_path = REPO_ROOT / relative_path
            assert evidence_path.is_file(), (
                f"{scenario['id']} references missing evidence {relative_path}"
            )
