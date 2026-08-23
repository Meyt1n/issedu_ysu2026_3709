"""Aggregate the P0 core-capability evidence into one honest decision.

The aggregator is intentionally fail-closed: missing reports or synthetic-only
reports block the release summary.  It is an evidence index, not a replacement
for the individual HCT-201/HCT-203/HCT-205/HCT-302/HCT-308/HCT-403/HCT-405/
HCT-409 reviews.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_REPORTS = {
    "HCT-201": ("hct201-fixed-set.json", {"ALLOW_APPROVED_FIXED_SET"}),
    "HCT-205": ("hct205-accuracy.json", {"ACCEPT_OCR_BARCODE_MASTER_DATA"}),
    "HCT-203-YOLO": ("hct203-yolo.json", {"READY_FOR_R3_REVIEW"}),
    "HCT-203-QLoRA": ("hct203-qlora.json", {"READY_FOR_R3_REVIEW"}),
    "HCT-302": ("hct302-rules.json", {"ACCEPT_RULES"}),
    "HCT-308": ("hct308-reminders.json", {"ACCEPT_REMINDER_FLOW"}),
    "HCT-403": ("hct403-assistant.json", {"READY_FOR_R3_REVIEW"}),
    "HCT-305": ("hct305-weather.json", {"LIVE_PROVIDER_VERIFIED"}),
    "HCT-405": ("hct405-core-e2e.json", {"ACCEPT_CORE_E2E"}),
    "HCT-409": ("hct409-release.json", {"READY_FOR_R3_REVIEW"}),
}


def aggregate(evidence_dir: Path) -> dict[str, Any]:
    gates: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []
    for gate, (filename, accepted) in REQUIRED_REPORTS.items():
        path = evidence_dir / filename
        if not path.is_file():
            finding = {"code": "REPORT_MISSING", "message": f"{gate}: missing {filename}"}
            gates.append(
                {"gate": gate, "report": filename, "status": "BLOCK", "findings": [finding]}
            )
            blockers.append({"gate": gate, **finding})
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            finding = {"code": "REPORT_INVALID", "message": f"{gate}: {exc}"}
            gates.append(
                {"gate": gate, "report": filename, "status": "BLOCK", "findings": [finding]}
            )
            blockers.append({"gate": gate, **finding})
            continue
        decision = value.get("decision") if isinstance(value, dict) else None
        passed = isinstance(value, dict) and value.get("passed") is True and decision in accepted
        status = "PASS" if passed else "BLOCK"
        finding_list = (
            [] if passed else [{"code": "GATE_NOT_PASSED", "message": f"decision={decision!r}"}]
        )
        gates.append(
            {
                "gate": gate,
                "report": filename,
                "status": status,
                "decision": decision,
                "findings": finding_list,
            }
        )
        if not passed:
            blockers.append(
                {"gate": gate, "code": "GATE_NOT_PASSED", "message": f"decision={decision!r}"}
            )
    passed = not blockers
    return {
        "schema_version": "hct-p0-acceptance/v1",
        "passed": passed,
        "decision": "READY_FOR_R3_REVIEW" if passed else "BLOCK_P0_ACCEPTANCE",
        "gates": gates,
        "blockers": blockers,
        "limitations": [
            "This summary cannot turn synthetic fixtures into production evidence.",
            "R3 approval, restart/offline drill and owner sign-off remain human decisions.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = aggregate(args.evidence_dir)
    report["evidence_dir_name"] = args.evidence_dir.name
    report["evidence_index_sha256"] = hashlib.sha256(
        json.dumps(report["gates"], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
