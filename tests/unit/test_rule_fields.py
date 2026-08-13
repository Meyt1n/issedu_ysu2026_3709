"""Unit tests for the deterministic rule-based field candidate layer."""

from __future__ import annotations

from ai.vision.evidence_pipeline import (
    BarcodeCandidate,
    EvidencePipelineRequest,
    EvidenceRegion,
    OCRToken,
    PackageRegionProposal,
    process_evidence,
)
from ai.vision.rule_fields import propose_fields


def _token(token_id: str, value: str, confidence: float = 0.95) -> OCRToken:
    return OCRToken(
        id=token_id,
        raw_value=value,
        region=EvidenceRegion(x=10, y=10, width=200, height=40),
        confidence=confidence,
        engine_version="paddleocr-test",
        language="zh-Hans",
    )


def test_line_level_ocr_yields_subtokens_and_fields() -> None:
    tokens = [
        _token("ocr-1", "DEMO MED A", 0.96),
        _token("ocr-2", "0.25g x 24"),
        _token("ocr-3", "LOT A12345  EXP 2027-05"),
    ]
    subtokens, proposals = propose_fields(tokens)

    by_field = {proposal.field_name: proposal for proposal in proposals}
    assert by_field["batch_number"].raw_value == "A12345"
    assert by_field["expiry_date"].raw_value == "2027-05"
    assert by_field["specification"].raw_value == "0.25g x 24"
    assert by_field["drug_name"].raw_value == "DEMO MED A"

    # spec/name tokens match whole lines -> parent referenced, no sub-token
    assert by_field["specification"].evidence_ids == ["ocr-2"]
    assert by_field["drug_name"].evidence_ids == ["ocr-1"]
    # batch/expiry live inside one line -> verbatim sub-tokens with the
    # parent's region and provenance
    subtoken_ids = {token.id for token in subtokens}
    assert set(by_field["batch_number"].evidence_ids) <= subtoken_ids
    assert set(by_field["expiry_date"].evidence_ids) <= subtoken_ids
    for token in subtokens:
        assert token.raw_value in "LOT A12345  EXP 2027-05"
        assert token.region is not None and token.region.x == 10
        assert token.engine_version == "paddleocr-test"

    assert all(proposal.source == "rule" for proposal in proposals)


def test_chinese_fixture_and_production_date_guard() -> None:
    tokens = [
        _token("ocr-1", "演示药甲片", 0.97),
        _token("ocr-2", "0.25g×24片"),
        _token("ocr-3", "2027-05"),
        _token("ocr-4", "生产日期2026-01-01"),
    ]
    _, proposals = propose_fields(tokens)
    by_field: dict[str, list] = {}
    for proposal in proposals:
        by_field.setdefault(proposal.field_name, []).append(proposal)

    assert by_field["drug_name"][0].raw_value == "演示药甲片"
    assert by_field["specification"][0].raw_value == "0.25g×24片"
    # a bare-date token is proposed as expiry; the production date is not
    expiry_values = [proposal.raw_value for proposal in by_field["expiry_date"]]
    assert expiry_values == ["2027-05"]


def test_barcode_and_packaging_proposals() -> None:
    barcode = BarcodeCandidate(
        id="code-1",
        raw_value="4006381333931",
        confidence=0.95,
        format="EAN-13",
        decoder_version="opencv-test",
        decode_valid=True,
        checksum_valid=True,
    )
    region = PackageRegionProposal(
        id="yolo-1",
        label="medicine_box",
        region=EvidenceRegion(x=0, y=0, width=100, height=100),
        confidence=0.9,
        model_version="yolo-test",
    )
    _, proposals = propose_fields([], [barcode], [region])
    by_field = {proposal.field_name: proposal for proposal in proposals}
    assert by_field["product_barcode"].evidence_ids == ["code-1"]
    assert by_field["packaging_type"].raw_value == "medicine_box"


def test_rule_proposals_survive_evidence_pipeline() -> None:
    tokens = [
        _token("ocr-1", "DEMO MED A", 0.96),
        _token("ocr-2", "0.25g x 24"),
        _token("ocr-3", "LOT A12345  EXP 2027-05"),
    ]
    subtokens, proposals = propose_fields(tokens)
    request = EvidencePipelineRequest(
        ocr_tokens=tokens + subtokens,
        field_proposals=proposals,
        ocr_engine_version="paddleocr-test",
    )
    result = process_evidence(request)

    stored = {item.field_name for item in result.fields}
    assert {"drug_name", "specification", "batch_number", "expiry_date"} <= stored
    rejected = [
        finding.code
        for finding in result.findings
        if finding.code
        in {"FIELD_VALUE_NOT_IN_EVIDENCE", "EVIDENCE_REFERENCE_MISSING"}
    ]
    assert rejected == []
    expiry = next(item for item in result.fields if item.field_name == "expiry_date")
    assert expiry.normalized_value == "2027-05"
    assert result.requires_human_confirmation is True
