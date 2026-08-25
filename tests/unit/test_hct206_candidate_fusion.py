from __future__ import annotations

import pytest
from ai.vision.candidate_fusion import (
    CalibrationSample,
    FusionStatus,
    calibrate_thresholds,
    fuse_evidence,
)
from ai.vision.evidence_pipeline import (
    BarcodeCandidate,
    EvidencePipelineRequest,
    FieldProposal,
    LocalMasterData,
    MasterDataRecord,
    OCRToken,
    process_evidence,
)


def _evidence(*, barcode: str = "4006381333931", name: str = "Demo Medicine"):
    request = EvidencePipelineRequest(
        ocr_tokens=[
            OCRToken(id="ocr-name", raw_value=name, confidence=0.95, engine_version="ocr-v1"),
            OCRToken(id="ocr-spec", raw_value="10mg", confidence=0.95, engine_version="ocr-v1"),
            OCRToken(
                id="ocr-maker", raw_value="Demo Labs", confidence=0.95, engine_version="ocr-v1"
            ),
            OCRToken(id="ocr-batch", raw_value="B123", confidence=0.95, engine_version="ocr-v1"),
            OCRToken(
                id="ocr-expiry", raw_value="2030-01", confidence=0.95, engine_version="ocr-v1"
            ),
            OCRToken(
                id="ocr-pack", raw_value="medicine_box", confidence=0.95, engine_version="ocr-v1"
            ),
        ],
        barcodes=[
            BarcodeCandidate(
                id="barcode-1",
                raw_value=barcode,
                format="EAN-13",
                confidence=0.98,
                decoder_version="barcode-v1",
            )
        ],
        field_proposals=[
            FieldProposal(
                field_name="drug_name",
                raw_value=name,
                evidence_ids=["ocr-name"],
                confidence=0.93,
                parser_version="parser-v1",
            ),
            FieldProposal(
                field_name="specification",
                raw_value="10mg",
                evidence_ids=["ocr-spec"],
                confidence=0.93,
                parser_version="parser-v1",
            ),
            FieldProposal(
                field_name="manufacturer",
                raw_value="Demo Labs",
                evidence_ids=["ocr-maker"],
                confidence=0.93,
                parser_version="parser-v1",
            ),
            FieldProposal(
                field_name="batch_number",
                raw_value="B123",
                evidence_ids=["ocr-batch"],
                confidence=0.93,
                parser_version="parser-v1",
            ),
            FieldProposal(
                field_name="expiry_date",
                raw_value="2030-01",
                evidence_ids=["ocr-expiry"],
                confidence=0.93,
                parser_version="parser-v1",
            ),
            FieldProposal(
                field_name="product_barcode",
                raw_value=barcode,
                evidence_ids=["barcode-1"],
                confidence=0.93,
                parser_version="parser-v1",
            ),
            FieldProposal(
                field_name="packaging_type",
                raw_value="medicine_box",
                evidence_ids=["ocr-pack"],
                confidence=0.93,
                parser_version="parser-v1",
            ),
        ],
        vision_model_version="yolo-v1",
        ocr_engine_version="ocr-v1",
        barcode_decoder_version="barcode-v1",
        master_data_version="master-v1",
    )
    master = LocalMasterData(
        version="master-v1",
        available=True,
        records=[
            MasterDataRecord(
                record_id="demo-1",
                product_barcode="4006381333931",
                name_aliases=["Demo Medicine"],
                specification="10mg",
                manufacturer="Demo Labs",
                packaging_type="medicine_box",
            ),
            MasterDataRecord(
                record_id="other-1",
                product_barcode="4006381333931",
                name_aliases=["Other Medicine"],
            ),
        ],
    )
    return process_evidence(request, master_data=master), master


def test_consistent_channels_are_ranked_and_require_confirmation() -> None:
    evidence, master = _evidence()
    result = fuse_evidence(evidence, master)

    assert result.status == FusionStatus.MATCHED
    assert result.selected_candidate_id == "demo-1"
    assert result.candidates[0].channel_evidence["ocr"].support == ["ocr-name"]
    assert result.candidates[0].channel_evidence["barcode"].support == ["barcode-1"]
    assert result.requires_human_confirmation is True
    assert result.health_event_allowed is False


def test_conflicting_barcode_and_name_never_match() -> None:
    evidence, master = _evidence(barcode="4006381333932")
    result = fuse_evidence(evidence, master)

    assert result.status in {FusionStatus.CONFLICT, FusionStatus.UNKNOWN, FusionStatus.REVIEW}
    assert result.status != FusionStatus.MATCHED
    assert "BARCODE_INVALID_CHECKSUM" in result.reasons


def test_unknown_master_data_is_safe() -> None:
    evidence, _ = _evidence()
    result = fuse_evidence(
        evidence,
        LocalMasterData(version="missing", available=False, records=[]),
    )

    assert result.status == FusionStatus.UNKNOWN
    assert result.candidates == []
    assert result.health_event_allowed is False


def test_calibration_is_versioned_and_evaluates_independent_split() -> None:
    validation = [
        CalibrationSample(
            sample_id="v-match",
            top_score=0.9,
            score_margin=0.3,
            expected_status="MATCHED",
            predicted_candidate_id="a",
            expected_candidate_id="a",
        ),
        CalibrationSample(
            sample_id="v-conflict",
            top_score=0.95,
            score_margin=0.2,
            expected_status="CONFLICT",
            observed_conflict=True,
            predicted_candidate_id="a",
            expected_candidate_id="b",
        ),
    ]
    independent = [
        CalibrationSample(
            sample_id="t-review",
            top_score=0.7,
            score_margin=0.02,
            expected_status="REVIEW",
            observed_review=True,
        )
    ]

    report = calibrate_thresholds(validation, independent)

    assert report.schema_version == "fusion-calibration-report-v1"
    assert len(report.sample_sha256) == 64
    assert report.independent_test.sample_count == 1
    assert report.thresholds.config_version == "fusion-thresholds-calibrated-v1"


def test_calibration_requires_both_splits() -> None:
    sample = CalibrationSample(
        sample_id="one", top_score=0.1, score_margin=0, expected_status="UNKNOWN"
    )
    with pytest.raises(ValueError, match="FUSION_CALIBRATION_SPLITS_REQUIRED"):
        calibrate_thresholds([sample], [])


def test_default_fusion_thresholds_match_registered_calibration() -> None:
    import json
    from pathlib import Path

    from ai.vision.candidate_fusion import FusionThresholds

    thresholds = FusionThresholds()
    registry = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "model-registry"
            / "HCT-206-fusion-thresholds-calibrated-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert thresholds.config_version == registry["config_version"]
    assert thresholds.matched_score == registry["thresholds"]["matched_score"]
    assert thresholds.unknown_score == registry["thresholds"]["unknown_score"]
    assert thresholds.min_margin == registry["thresholds"]["min_margin"]
    assert registry["production_eligible"] is False
    assert "fusion-thresholds-demo-v1" in registry["supersedes"]
