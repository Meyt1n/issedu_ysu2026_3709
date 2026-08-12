"""Run the reproducible HCT-206 technical calibration fixture.

The fixture is deliberately synthetic and is approved only for deterministic
fusion-rule regression.  This command must never be used to claim production
medicine accuracy; HCT-201 remains the production data and release gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# ``uv run python scripts/hct206_calibrate.py`` starts with ``scripts/`` as
# ``sys.path[0]``; add the source root explicitly for the documented command.
sys.path.insert(0, str(ROOT / "src"))
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "hct206" / "calibration_fixture.json"
FIXTURE_SCHEMA_VERSION = "hct206-calibration-fixture-v1"


def load_fixture(path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    if fixture.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise ValueError("HCT206_CALIBRATION_FIXTURE_SCHEMA_INVALID")
    approval = fixture.get("approval", {})
    if approval.get("status") != "APPROVED_FOR_TECHNICAL_CALIBRATION":
        raise ValueError("HCT206_CALIBRATION_FIXTURE_NOT_APPROVED")
    if fixture.get("production_eligible") is not False:
        raise ValueError("HCT206_CALIBRATION_FIXTURE_MUST_NOT_BE_PRODUCTION")
    if fixture.get("source", {}).get("type") != "synthetic":
        raise ValueError("HCT206_CALIBRATION_FIXTURE_MUST_BE_SYNTHETIC")
    validation = fixture.get("validation")
    independent = fixture.get("independent_test")
    if not isinstance(validation, list) or not validation:
        raise ValueError("HCT206_VALIDATION_SPLIT_REQUIRED")
    if not isinstance(independent, list) or not independent:
        raise ValueError("HCT206_INDEPENDENT_SPLIT_REQUIRED")
    validation_ids = {str(sample.get("sample_id")) for sample in validation}
    independent_ids = {str(sample.get("sample_id")) for sample in independent}
    if len(validation_ids) != len(validation) or len(independent_ids) != len(independent):
        raise ValueError("HCT206_CALIBRATION_SAMPLE_IDS_MUST_BE_UNIQUE")
    if validation_ids & independent_ids:
        raise ValueError("HCT206_CALIBRATION_SPLITS_MUST_BE_DISJOINT")
    return fixture


def run_calibration(path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    from ai.vision.candidate_fusion import CalibrationSample, calibrate_thresholds

    fixture = load_fixture(path)
    validation = [CalibrationSample.model_validate(item) for item in fixture["validation"]]
    independent = [CalibrationSample.model_validate(item) for item in fixture["independent_test"]]
    report = calibrate_thresholds(validation, independent)
    return {
        "fixture_id": fixture["fixture_id"],
        "fixture_schema_version": fixture["schema_version"],
        "approval": fixture["approval"],
        "production_eligible": fixture["production_eligible"],
        "report": report.model_dump(mode="json"),
        "limitations": fixture["limitations"],
        "human_review": fixture["human_review"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_calibration(args.fixture)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
