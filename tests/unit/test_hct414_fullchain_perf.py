"""HCT-414 / #246 剩余项第 2 条：守住全链路性能报告的契约与安全声明。

与 ``test_hct414_video_perf.py`` 同思路：不断言具体毫秒数（那取决于机器），
只断言报告结构、必须存在的披露，以及「本应拒绝的样例确实被拒绝」。
"""

from __future__ import annotations

import json

import pytest

import hct414_fullchain_perf as probe

pytest.importorskip("cv2")


def test_ean13_checksum_matches_known_values() -> None:
    assert probe.ean13_checksum("400638133393") == "1"
    assert probe.ean13_modules(probe.VALID_BARCODE).__len__() == 95
    assert probe.ean13_modules(probe.VALID_BARCODE).startswith("101")
    assert probe.ean13_modules(probe.VALID_BARCODE).endswith("101")


def test_bad_checksum_barcode_is_still_renderable() -> None:
    """受控拒绝样例必须能画出来，否则测不到「解码成功但校验位错」这条路径。"""
    assert probe.ean13_checksum(probe.BAD_CHECKSUM_BARCODE[:12]) != probe.BAD_CHECKSUM_BARCODE[12]
    assert len(probe.ean13_modules(probe.BAD_CHECKSUM_BARCODE)) == 95


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    workdir = tmp_path_factory.mktemp("hct414-fullchain")
    return probe.build_report(3, workdir)


def test_report_schema_and_stage_coverage(report: dict) -> None:
    assert report["schema_version"] == probe.REPORT_SCHEMA
    stages = report["stages_measured"]
    assert set(stages) == {"barcode_decode", "evidence_normalize", "fusion_match"}
    for stats in stages.values():
        assert stats["count"] == 3
        assert stats["p50_ms"] >= 0
        assert stats["p95_ms"] >= 0
        assert stats["max_ms"] >= stats["p50_ms"]
    assert report["chain"]["count"] == 3
    assert report["chain_p95_budget_ms"] == probe.CHAIN_P95_BUDGET_MS


def test_fixture_is_hashed_and_decodable(report: dict) -> None:
    fixture = report["fixture"]
    assert len(fixture["sha256"]) == 64
    assert fixture["size_bytes"] > 0
    assert fixture["decoded_value"] == probe.VALID_BARCODE
    assert fixture["render"] is not None, "必须记录命中的渲染参数，否则无法复现"
    assert "opencv" in fixture["decoder_version"]


def test_matched_case_still_requires_human_confirmation(report: dict) -> None:
    matched = report["matched_case"]
    assert matched["status"] == "MATCHED"
    assert matched["requires_human_confirmation"] is True
    assert matched["health_event_allowed"] is False


def test_all_controlled_rejections_are_rejected(report: dict) -> None:
    samples = {item["sample"]: item for item in report["failure_samples"]}
    assert set(samples) == {
        "barcode_bad_checksum",
        "master_data_unavailable",
        "blank_image_no_barcode",
        "name_conflicts_master_data",
    }
    for name, item in samples.items():
        assert item["rejected"] is True, f"{name} 本应被拒绝"
        assert item["health_event_allowed"] is False
    assert report["unexpectedly_accepted"] == []


def test_ocr_is_disclosed_not_silently_skipped(report: dict) -> None:
    """OCR 未测这件事必须在报告里说出来，不许静默省略。"""
    assert "ocr" in report
    assert isinstance(report["ocr"]["available"], bool)
    not_measured = " ".join(report["stages_not_measured"])
    assert "OCR" in not_measured
    assert "人工复核" in not_measured
    assert "并发" in not_measured
    if not report["ocr"]["available"]:
        assert report["ocr"]["unavailable_reason"]


def test_release_status_stays_demo_only(report: dict) -> None:
    assert report["release_status"] == "DEMO_ONLY"
    blockers = " ".join(report["release_blockers"])
    assert "HCT-201" in blockers
    assert report["privacy"]["real_medicine_photos"] is False
    assert report["privacy"]["real_health_data"] is False
    assert report["privacy"]["synthetic_fixtures_only"] is True


def test_report_is_json_serialisable(report: dict) -> None:
    text = json.dumps(report, ensure_ascii=False)
    assert probe.REPORT_SCHEMA in text
