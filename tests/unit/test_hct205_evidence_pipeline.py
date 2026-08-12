from __future__ import annotations

from ai.vision.evidence_pipeline import (
    BarcodeCandidate,
    EvidencePipelineRequest,
    FieldProposal,
    LocalMasterData,
    MasterDataRecord,
    OCRToken,
    process_evidence,
)


def _ocr(*, token_id: str = "ocr-name", value: str = "  Demo  Medicine ") -> OCRToken:
    return OCRToken(
        id=token_id,
        raw_value=value,
        confidence=0.92,
        engine_version="ocr-demo-v1",
    )


def test_normalizes_field_only_from_existing_ocr_evidence() -> None:
    request = EvidencePipelineRequest(
        ocr_tokens=[_ocr()],
        field_proposals=[
            FieldProposal(
                field_name="drug_name",
                raw_value="Demo Medicine",
                evidence_ids=["ocr-name"],
                confidence=0.88,
                parser_version="rules-v1",
            )
        ],
    )

    result = process_evidence(request)

    assert result.evidence[0].original_value == "  Demo  Medicine "
    assert result.fields[0].normalized_value == "Demo Medicine"
    assert result.fields[0].confirmation_status == "UNCONFIRMED"
    assert "FIELD_VALUE_NOT_IN_EVIDENCE" not in {finding.code for finding in result.findings}
    assert result.fusion_readiness == "UNKNOWN"
    assert result.requires_human_confirmation is True


def test_valid_barcode_and_local_master_are_candidates_not_confirmation() -> None:
    request = EvidencePipelineRequest(
        ocr_tokens=[_ocr()],
        barcodes=[
            BarcodeCandidate(
                id="barcode-1",
                raw_value="4006381333931",
                format="EAN-13",
                confidence=0.99,
                decoder_version="zxing-local-v1",
            )
        ],
        field_proposals=[
            FieldProposal(
                field_name="drug_name",
                raw_value="Demo Medicine",
                evidence_ids=["ocr-name"],
                confidence=0.88,
                parser_version="rules-v1",
            )
        ],
    )
    master = LocalMasterData(
        version="demo-master-v1",
        available=True,
        records=[
            MasterDataRecord(
                record_id="demo-record-1",
                product_barcode="4006381333931",
                name_aliases=["Demo Medicine"],
            )
        ],
    )

    result = process_evidence(request, master_data=master)

    assert result.barcodes[0].validation_status == "VALID"
    assert result.master_candidates[0].record_id == "demo-record-1"
    assert result.master_candidates[0].reasons == ["BARCODE_EXACT", "NAME_EXACT"]
    assert result.fusion_readiness == "REVIEW"
    assert result.requires_human_confirmation is True


def test_invalid_barcode_is_structured_and_unknown_without_candidate() -> None:
    request = EvidencePipelineRequest(
        barcodes=[
            BarcodeCandidate(
                id="barcode-bad",
                raw_value="4006381333932",
                format="EAN-13",
                confidence=0.96,
                decoder_version="zxing-local-v1",
            )
        ]
    )

    result = process_evidence(request)

    assert result.barcodes[0].validation_status == "INVALID_CHECKSUM"
    assert "BARCODE_INVALID_CHECKSUM" in {finding.code for finding in result.findings}
    assert result.master_candidates == []
    assert result.fusion_readiness == "UNKNOWN"


def test_field_proposal_cannot_invent_text_or_reference_missing_evidence() -> None:
    request = EvidencePipelineRequest(
        ocr_tokens=[_ocr(value="包装")],
        field_proposals=[
            FieldProposal(
                field_name="manufacturer",
                raw_value="Invented Manufacturer",
                evidence_ids=["missing-token"],
                confidence=0.99,
                parser_version="llm-structure-v1",
                source="llm",
            )
        ],
    )

    result = process_evidence(request)
    codes = {finding.code for finding in result.findings}

    assert result.fields == []
    assert "EVIDENCE_REFERENCE_MISSING" in codes
    assert result.fusion_readiness == "UNKNOWN"


def test_referenced_value_mismatch_is_not_emitted_as_field_evidence() -> None:
    result = process_evidence(
        EvidencePipelineRequest(
            ocr_tokens=[_ocr(value="Observed text")],
            field_proposals=[
                FieldProposal(
                    field_name="manufacturer",
                    raw_value="Invented Manufacturer",
                    evidence_ids=["ocr-name"],
                    confidence=0.99,
                    parser_version="llm-structure-v1",
                    source="llm",
                )
            ],
        )
    )

    assert result.fields == []
    assert "FIELD_VALUE_NOT_IN_EVIDENCE" in {finding.code for finding in result.findings}


def test_yolo_cannot_be_the_only_source_for_identity_fields() -> None:
    result = process_evidence(
        EvidencePipelineRequest(
            package_regions=[
                {
                    "id": "yolo-box",
                    "label": "medicine_box",
                    "region": {"x": 1, "y": 1, "width": 10, "height": 10},
                    "confidence": 0.9,
                    "model_version": "yolo-experimental-v1",
                }
            ],
            field_proposals=[
                FieldProposal(
                    field_name="drug_name",
                    raw_value="Invented Medicine",
                    evidence_ids=["yolo-box"],
                    confidence=0.9,
                    parser_version="rules-v1",
                )
            ],
        )
    )

    assert result.fields == []
    assert "FIELD_SOURCE_CHANNEL_UNSAFE" in {finding.code for finding in result.findings}


def test_duplicate_evidence_reference_is_not_consumable() -> None:
    result = process_evidence(
        EvidencePipelineRequest(
            ocr_tokens=[_ocr(token_id="same"), _ocr(token_id="same", value="Other")],
            field_proposals=[
                FieldProposal(
                    field_name="drug_name",
                    raw_value="Demo Medicine",
                    evidence_ids=["same"],
                    confidence=0.9,
                    parser_version="rules-v1",
                )
            ],
        )
    )

    assert result.fields == []
    assert "DUPLICATE_EVIDENCE_ID" in {finding.code for finding in result.findings}
    assert "EVIDENCE_REFERENCE_AMBIGUOUS" in {finding.code for finding in result.findings}
