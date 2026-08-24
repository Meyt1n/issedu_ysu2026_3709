"""Pure tests for the HCT-405 local evidence collector."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.hct405_local_evidence import collect_evidence  # noqa: E402


def test_local_evidence_report_keeps_external_acceptance_blocked(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.hct405_local_evidence.probe",
        lambda _url, path: {"result": "PASS", "evidence_ref": path},
    )
    monkeypatch.setattr(
        "scripts.hct405_local_evidence.run_automated_tests",
        lambda: {"result": "PASS", "synthetic_only": True},
    )

    report = collect_evidence(api_url="http://api", web_url="http://web")

    assert report["decision"] == "LOCAL_EVIDENCE_COLLECTED_NOT_ACCEPTANCE"
    assert report["manual_or_external_evidence_required"]
    assert report["automated_tests"]["synthetic_only"] is True
