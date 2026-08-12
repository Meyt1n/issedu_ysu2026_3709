"""HCT-205 OCR-first evidence contract and offline normalization.

This module deliberately does not run OCR or identify a medicine.  Adapter
outputs are treated as evidence only:

* OCR keeps the original text, region, confidence and engine version.
* Barcode decoding is an independent channel with format/check-digit status.
* YOLO proposals are crop hints and never become identity evidence.
* Local master data is optional and offline; an unavailable or empty index
  cannot manufacture a candidate.

HCT-206 owns candidate fusion and the final four-state decision.  This module
therefore never emits ``MATCHED`` and always requires human confirmation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "ocr-first-evidence-v1"
NORMALIZER_VERSION = "evidence-normalizer-v1"
REQUIRED_FIELDS = (
    "drug_name",
    "specification",
    "manufacturer",
    "batch_number",
    "expiry_date",
    "product_barcode",
    "packaging_type",
)

FieldName = Literal[
    "drug_name",
    "specification",
    "manufacturer",
    "batch_number",
    "expiry_date",
    "product_barcode",
    "packaging_type",
]
EvidenceChannel = Literal["ocr", "barcode", "yolo"]
BarcodeFormat = Literal["EAN-8", "EAN-13", "UPC-A", "ITF-14", "QR", "DATA_MATRIX", "UNKNOWN"]


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRegion(EvidenceModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    coordinate_space: Literal["pixel", "normalized"] = "pixel"


class OCRToken(EvidenceModel):
    id: str = Field(min_length=1, max_length=128)
    channel: Literal["ocr"] = "ocr"
    raw_value: str = Field(min_length=1, max_length=2048)
    region: EvidenceRegion | None = None
    confidence: float = Field(ge=0, le=1)
    engine_version: str = Field(min_length=1, max_length=128)
    language: str = Field(default="und", min_length=1, max_length=32)


class BarcodeCandidate(EvidenceModel):
    id: str = Field(min_length=1, max_length=128)
    channel: Literal["barcode"] = "barcode"
    raw_value: str = Field(min_length=1, max_length=2048)
    region: EvidenceRegion | None = None
    confidence: float = Field(ge=0, le=1)
    format: BarcodeFormat = "UNKNOWN"
    decoder_version: str = Field(min_length=1, max_length=128)
    checksum_valid: bool | None = None
    decode_valid: bool = False


class PackageRegionProposal(EvidenceModel):
    id: str = Field(min_length=1, max_length=128)
    channel: Literal["yolo"] = "yolo"
    label: str = Field(min_length=1, max_length=80)
    region: EvidenceRegion
    confidence: float = Field(ge=0, le=1)
    model_version: str = Field(min_length=1, max_length=128)


class FieldProposal(EvidenceModel):
    field_name: FieldName
    raw_value: str = Field(min_length=1, max_length=2048)
    evidence_ids: list[str] = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0, le=1)
    parser_version: str = Field(min_length=1, max_length=128)
    source: Literal["rule", "llm", "manual"] = "rule"


class EvidencePipelineRequest(EvidenceModel):
    """Adapter output submitted after the quality gate.

    ``field_proposals`` are constrained to references to existing evidence;
    a caller cannot submit a free-standing field and call it a fact.
    """

    ocr_tokens: list[OCRToken] = Field(default_factory=list, max_length=512)
    barcodes: list[BarcodeCandidate] = Field(default_factory=list, max_length=64)
    package_regions: list[PackageRegionProposal] = Field(default_factory=list, max_length=64)
    field_proposals: list[FieldProposal] = Field(default_factory=list, max_length=64)
    vision_model_version: str = Field(default="unavailable", min_length=1, max_length=128)
    ocr_engine_version: str = Field(default="unavailable", min_length=1, max_length=128)
    barcode_decoder_version: str = Field(default="unavailable", min_length=1, max_length=128)
    master_data_version: str = Field(default="unavailable", min_length=1, max_length=128)
    code_version: str = Field(default="hct-205-d1", min_length=1, max_length=128)
    adapter_id: str = Field(default="homecare-local-vision", min_length=1, max_length=128)
    adapter_version: str = Field(default="adapter-unavailable", min_length=1, max_length=128)
    adapter_run_id: str = Field(default="run-unavailable", min_length=1, max_length=128)
    adapter_receipt: str | None = Field(default=None, min_length=32, max_length=512)


class NormalizedEvidence(EvidenceModel):
    id: str
    channel: EvidenceChannel
    original_value: str
    normalized_value: str
    region: EvidenceRegion | None = None
    confidence: float = Field(ge=0, le=1)
    producer_version: str


class BarcodeEvidenceResult(EvidenceModel):
    evidence_id: str
    original_value: str
    normalized_value: str
    format: BarcodeFormat
    validation_status: Literal["VALID", "INVALID_FORMAT", "INVALID_CHECKSUM"]
    checksum_valid: bool | None
    confidence: float = Field(ge=0, le=1)
    decoder_version: str


class FieldEvidence(EvidenceModel):
    field_name: FieldName
    original_value: str
    normalized_value: str
    evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)
    parser_version: str
    model_version: str
    source: Literal["rule", "llm", "manual"]
    confirmation_status: Literal["UNCONFIRMED"] = "UNCONFIRMED"


class EvidenceFinding(EvidenceModel):
    code: str
    severity: Literal["INFO", "REVIEW", "CONFLICT"]
    channel: Literal["ocr", "barcode", "yolo", "field", "master", "pipeline"]
    detail: str


class MasterDataRecord(EvidenceModel):
    record_id: str = Field(min_length=1, max_length=128)
    product_barcode: str | None = None
    name_aliases: list[str] = Field(default_factory=list, max_length=32)
    specification: str | None = None
    manufacturer: str | None = None
    packaging_type: str | None = None

    @field_validator("product_barcode")
    @classmethod
    def normalize_optional_barcode(cls, value: str | None) -> str | None:
        return _normalize_barcode(value) if value else value


class LocalMasterData(EvidenceModel):
    version: str = Field(min_length=1, max_length=128)
    available: bool = False
    records: list[MasterDataRecord] = Field(default_factory=list, max_length=10000)


class MasterCandidate(EvidenceModel):
    record_id: str
    reasons: list[Literal["BARCODE_EXACT", "NAME_EXACT"]]


class EvidencePipelineResult(EvidenceModel):
    schema_version: str = SCHEMA_VERSION
    source_sha256: str | None = None
    source_digest_scope: Literal["uploaded_file_bytes"] = "uploaded_file_bytes"
    evidence: list[NormalizedEvidence]
    barcodes: list[BarcodeEvidenceResult]
    fields: list[FieldEvidence]
    master_candidates: list[MasterCandidate]
    missing_fields: list[FieldName]
    findings: list[EvidenceFinding]
    fusion_readiness: Literal["READY_FOR_FUSION", "REVIEW", "UNKNOWN", "CONFLICT"]
    requires_human_confirmation: Literal[True] = True
    versions: dict[str, str]


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split())


def _normalize_barcode(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def _normalize_expiry(value: str) -> str:
    normalized = _normalize_text(value)
    match = re.fullmatch(
        r"(20\d{2})\s*[年./-]\s*(\d{1,2})(?:\s*[月./-]\s*(\d{1,2})\s*日?)?", normalized
    )
    if match is None:
        return normalized
    year, month, day = match.groups()
    if day is None:
        return f"{year}-{int(month):02d}"
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _normalize_field(field_name: FieldName, value: str) -> str:
    if field_name == "product_barcode":
        return _normalize_barcode(value)
    if field_name == "expiry_date":
        return _normalize_expiry(value)
    return _normalize_text(value)


def _infer_barcode_format(value: str) -> BarcodeFormat:
    return {
        8: "EAN-8",
        12: "UPC-A",
        13: "EAN-13",
        14: "ITF-14",
    }.get(len(value), "UNKNOWN")  # type: ignore[return-value]


def _check_digit(value: str) -> bool:
    if not value.isdigit() or len(value) not in {8, 12, 13, 14}:
        return False
    body = value[:-1]
    weighted = sum(
        int(char) * (3 if index % 2 == 0 else 1) for index, char in enumerate(reversed(body))
    )
    return (weighted + int(value[-1])) % 10 == 0


def _validate_barcode(candidate: BarcodeCandidate) -> BarcodeEvidenceResult:
    normalized = _normalize_barcode(candidate.raw_value)
    inferred = _infer_barcode_format(normalized) if normalized.isdigit() else "UNKNOWN"
    declared = candidate.format
    numeric_format = declared not in {"QR", "DATA_MATRIX"}
    if numeric_format and (not normalized.isdigit() or inferred == "UNKNOWN"):
        status: Literal["VALID", "INVALID_FORMAT", "INVALID_CHECKSUM"] = "INVALID_FORMAT"
        checksum_valid = False
    elif declared != "UNKNOWN" and declared not in {inferred, "QR", "DATA_MATRIX"}:
        status = "INVALID_FORMAT"
        checksum_valid = False
    elif declared in {"QR", "DATA_MATRIX"}:
        status = "VALID" if candidate.decode_valid else "INVALID_FORMAT"
        checksum_valid = candidate.checksum_valid
    else:
        checksum_valid = _check_digit(normalized)
        status = "VALID" if checksum_valid else "INVALID_CHECKSUM"
    return BarcodeEvidenceResult(
        evidence_id=candidate.id,
        original_value=candidate.raw_value,
        normalized_value=normalized,
        format=declared if declared != "UNKNOWN" else inferred,
        validation_status=status,
        checksum_valid=checksum_valid,
        confidence=candidate.confidence,
        decoder_version=candidate.decoder_version,
    )


def _finding(
    code: str,
    severity: Literal["INFO", "REVIEW", "CONFLICT"],
    channel: Literal["ocr", "barcode", "yolo", "field", "master", "pipeline"],
    detail: str,
) -> EvidenceFinding:
    return EvidenceFinding(code=code, severity=severity, channel=channel, detail=detail)


def _unique_findings(findings: Sequence[EvidenceFinding]) -> list[EvidenceFinding]:
    unique: dict[tuple[str, str, str], EvidenceFinding] = {}
    for item in findings:
        unique[(item.code, item.channel, item.detail)] = item
    return sorted(unique.values(), key=lambda item: (item.channel, item.code, item.detail))


def _master_candidates(
    fields: Sequence[FieldEvidence],
    barcodes: Sequence[BarcodeEvidenceResult],
    master_data: LocalMasterData,
) -> list[MasterCandidate]:
    if not master_data.available:
        return []
    names = {field.normalized_value for field in fields if field.field_name == "drug_name"}
    valid_barcodes = {
        barcode.normalized_value for barcode in barcodes if barcode.validation_status == "VALID"
    }
    candidates: list[MasterCandidate] = []
    for record in master_data.records:
        reasons: list[Literal["BARCODE_EXACT", "NAME_EXACT"]] = []
        if record.product_barcode and record.product_barcode in valid_barcodes:
            reasons.append("BARCODE_EXACT")
        aliases = {_normalize_text(alias) for alias in record.name_aliases}
        if names & aliases:
            reasons.append("NAME_EXACT")
        if reasons:
            candidates.append(MasterCandidate(record_id=record.record_id, reasons=reasons))
    return candidates


def process_evidence(
    request: EvidencePipelineRequest,
    *,
    master_data: LocalMasterData | None = None,
    source_sha256: str | None = None,
) -> EvidencePipelineResult:
    """Normalize adapter evidence without confirming an identity.

    The function is deterministic for the same request and master-data
    snapshot.  It intentionally returns a safe state even when evidence is
    incomplete or malformed.
    """
    local_master = master_data or LocalMasterData(version="unavailable", available=False)
    all_ids = [
        item.id for item in (*request.ocr_tokens, *request.barcodes, *request.package_regions)
    ]
    duplicate_ids = {evidence_id for evidence_id, count in Counter(all_ids).items() if count > 1}
    findings: list[EvidenceFinding] = []
    if duplicate_ids:
        findings.append(
            _finding("DUPLICATE_EVIDENCE_ID", "REVIEW", "pipeline", "evidence IDs must be unique")
        )

    normalized_evidence: list[NormalizedEvidence] = []
    for token in request.ocr_tokens:
        normalized_evidence.append(
            NormalizedEvidence(
                id=token.id,
                channel="ocr",
                original_value=token.raw_value,
                normalized_value=_normalize_text(token.raw_value),
                region=token.region,
                confidence=token.confidence,
                producer_version=token.engine_version,
            )
        )
    for barcode in request.barcodes:
        normalized_evidence.append(
            NormalizedEvidence(
                id=barcode.id,
                channel="barcode",
                original_value=barcode.raw_value,
                normalized_value=_normalize_barcode(barcode.raw_value),
                region=barcode.region,
                confidence=barcode.confidence,
                producer_version=barcode.decoder_version,
            )
        )
    for proposal in request.package_regions:
        normalized_evidence.append(
            NormalizedEvidence(
                id=proposal.id,
                channel="yolo",
                original_value=proposal.label,
                normalized_value=_normalize_text(proposal.label),
                region=proposal.region,
                confidence=proposal.confidence,
                producer_version=proposal.model_version,
            )
        )

    barcode_results = [_validate_barcode(candidate) for candidate in request.barcodes]
    for barcode in barcode_results:
        if barcode.validation_status != "VALID":
            findings.append(
                _finding(
                    "BARCODE_" + barcode.validation_status,
                    "REVIEW",
                    "barcode",
                    f"barcode evidence {barcode.evidence_id} requires review",
                )
            )
    valid_barcode_values = [
        barcode.normalized_value
        for barcode in barcode_results
        if barcode.validation_status == "VALID"
    ]
    if len(set(valid_barcode_values)) > 1:
        findings.append(
            _finding("BARCODE_CONFLICT", "CONFLICT", "barcode", "valid barcode candidates disagree")
        )

    evidence_by_id = {item.id: item for item in normalized_evidence}
    confidence_by_id = {item.id: item.confidence for item in normalized_evidence}
    fields: list[FieldEvidence] = []
    for proposal in request.field_proposals:
        if any(evidence_id in duplicate_ids for evidence_id in proposal.evidence_ids):
            findings.append(
                _finding(
                    "EVIDENCE_REFERENCE_AMBIGUOUS",
                    "REVIEW",
                    "field",
                    f"field {proposal.field_name} references a duplicate evidence ID",
                )
            )
            continue
        referenced = [evidence_by_id.get(evidence_id) for evidence_id in proposal.evidence_ids]
        if any(item is None for item in referenced):
            findings.append(
                _finding(
                    "EVIDENCE_REFERENCE_MISSING",
                    "REVIEW",
                    "field",
                    f"field {proposal.field_name} has missing evidence",
                )
            )
            continue
        source_channels = {item.channel for item in referenced if item is not None}
        if proposal.field_name != "packaging_type" and not source_channels & {"ocr", "barcode"}:
            findings.append(
                _finding(
                    "FIELD_SOURCE_CHANNEL_UNSAFE",
                    "REVIEW",
                    "field",
                    f"field {proposal.field_name} cannot rely on YOLO alone",
                )
            )
            continue
        normalized = _normalize_field(proposal.field_name, proposal.raw_value)
        if not normalized:
            findings.append(
                _finding(
                    "FIELD_VALUE_EMPTY", "REVIEW", "field", f"field {proposal.field_name} is empty"
                )
            )
            continue
        source_values = {item.normalized_value for item in referenced if item is not None}
        if normalized not in source_values:
            findings.append(
                _finding(
                    "FIELD_VALUE_NOT_IN_EVIDENCE",
                    "REVIEW",
                    "field",
                    f"field {proposal.field_name} is not present in source evidence",
                )
            )
            continue
        fields.append(
            FieldEvidence(
                field_name=proposal.field_name,
                original_value=proposal.raw_value,
                normalized_value=normalized,
                evidence_ids=proposal.evidence_ids,
                confidence=min(
                    [
                        proposal.confidence,
                        *(
                            confidence_by_id[evidence_id]
                            for evidence_id in proposal.evidence_ids
                            if evidence_id in confidence_by_id
                        ),
                    ]
                ),
                parser_version=proposal.parser_version,
                model_version=request.vision_model_version,
                source=proposal.source,
            )
        )

    allowed_package_labels = {
        "medicine_box",
        "medicine_bottle",
        "blister_pack",
        "barcode_region",
        "health_report",
        "metric_table",
        "medical_advice_region",
    }
    for proposal in request.package_regions:
        if proposal.label not in allowed_package_labels:
            findings.append(
                _finding(
                    "PACKAGE_LABEL_UNKNOWN",
                    "REVIEW",
                    "yolo",
                    f"package proposal {proposal.id} has an uncontrolled label",
                )
            )

    by_field: dict[str, set[str]] = defaultdict(set)
    for field in fields:
        by_field[field.field_name].add(field.normalized_value)
    if any(len(values) > 1 for values in by_field.values()):
        findings.append(_finding("FIELD_CONFLICT", "CONFLICT", "field", "field proposals disagree"))
    missing_fields = [field for field in REQUIRED_FIELDS if field not in by_field]
    if missing_fields:
        findings.append(
            _finding("FIELDS_MISSING", "REVIEW", "field", "one or more approved fields are absent")
        )
    if not local_master.available:
        findings.append(
            _finding(
                "MASTER_DATA_UNAVAILABLE",
                "REVIEW",
                "master",
                "offline master data snapshot is unavailable",
            )
        )
    elif not local_master.records:
        findings.append(
            _finding(
                "MASTER_DATA_EMPTY", "REVIEW", "master", "offline master data snapshot is empty"
            )
        )

    candidates = _master_candidates(fields, barcode_results, local_master)
    if local_master.available and not candidates:
        findings.append(
            _finding(
                "MASTER_NO_MATCH", "REVIEW", "master", "no local master-data candidate matched"
            )
        )

    unique_findings = _unique_findings(findings)
    if any(item.severity == "CONFLICT" for item in unique_findings):
        readiness: Literal["READY_FOR_FUSION", "REVIEW", "UNKNOWN", "CONFLICT"] = "CONFLICT"
    elif not candidates:
        readiness = "UNKNOWN"
    elif any(item.severity == "REVIEW" for item in unique_findings):
        readiness = "REVIEW"
    else:
        readiness = "READY_FOR_FUSION"

    return EvidencePipelineResult(
        source_sha256=source_sha256,
        evidence=normalized_evidence,
        barcodes=barcode_results,
        fields=fields,
        master_candidates=candidates,
        missing_fields=missing_fields,
        findings=unique_findings,
        fusion_readiness=readiness,
        versions={
            "schema_version": SCHEMA_VERSION,
            "normalizer_version": NORMALIZER_VERSION,
            "vision_model_version": request.vision_model_version,
            "ocr_engine_version": request.ocr_engine_version,
            "barcode_decoder_version": request.barcode_decoder_version,
            "master_data_version": local_master.version,
            "code_version": request.code_version,
            "adapter_id": request.adapter_id,
            "adapter_version": request.adapter_version,
            "adapter_run_id": request.adapter_run_id,
        },
    )


def _adapter_payload_digest(request: EvidencePipelineRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"adapter_receipt"})
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def issue_adapter_receipt(
    task_id: str,
    input_digest: str,
    request: EvidencePipelineRequest,
    secret: str,
) -> str:
    """Create a local-only HMAC receipt for a complete adapter payload."""
    if not secret:
        raise ValueError("ADAPTER_SIGNING_KEY_UNAVAILABLE")
    message = "|".join(
        (
            "hct-adapter-receipt-v1",
            task_id,
            input_digest,
            _adapter_payload_digest(request),
            request.adapter_id,
            request.adapter_version,
            request.adapter_run_id,
        )
    ).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"hct-adapter-v1.{encoded}"


def verify_adapter_receipt(
    task_id: str,
    input_digest: str,
    request: EvidencePipelineRequest,
    secret: str,
) -> bool:
    if not request.adapter_receipt:
        return False
    expected = issue_adapter_receipt(task_id, input_digest, request, secret)
    return hmac.compare_digest(request.adapter_receipt, expected)
