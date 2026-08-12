"""Deterministic multi-evidence candidate fusion for HCT-206.

The fusion layer only ranks candidates already present in the approved local
master-data snapshot.  It never invents an identity, confirms a health fact,
or treats a single channel as sufficient for ``MATCHED``.  OCR, barcode,
packaging and metadata evidence are reported separately so a reviewer can see
support, conflict and missing evidence instead of only a total score.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence_pipeline import EvidencePipelineResult, LocalMasterData, MasterDataRecord

SCHEMA_VERSION = "candidate-fusion-v1"
RULE_VERSION = "fusion-rules-v1"
CALIBRATION_SCHEMA_VERSION = "fusion-calibration-report-v1"


class FusionStatus(StrEnum):
    MATCHED = "MATCHED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"
    REVIEW = "REVIEW"


class FusionWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ocr: float = Field(default=0.40, ge=0, le=1)
    barcode: float = Field(default=0.30, ge=0, le=1)
    packaging: float = Field(default=0.15, ge=0, le=1)
    metadata: float = Field(default=0.15, ge=0, le=1)
    version: str = Field(default="fusion-weights-v1", min_length=1, max_length=128)

    @model_validator(mode="after")
    def weights_must_sum_to_one(self) -> FusionWeights:
        if abs((self.ocr + self.barcode + self.packaging + self.metadata) - 1.0) > 1e-6:
            raise ValueError("FUSION_WEIGHTS_MUST_SUM_TO_ONE")
        return self


class FusionThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched_score: float = Field(default=0.80, ge=0, le=1)
    unknown_score: float = Field(default=0.35, ge=0, le=1)
    min_margin: float = Field(default=0.10, ge=0, le=1)
    config_version: str = Field(default="fusion-thresholds-demo-v1", min_length=1, max_length=128)

    @model_validator(mode="after")
    def thresholds_must_be_ordered(self) -> FusionThresholds:
        if self.unknown_score >= self.matched_score:
            raise ValueError("FUSION_THRESHOLDS_INVALID_ORDER")
        return self


class FusionRequest(BaseModel):
    """Optional threshold override accepted by the task fusion endpoint."""

    model_config = ConfigDict(extra="forbid")

    matched_score: float = Field(default=0.80, ge=0, le=1)
    unknown_score: float = Field(default=0.35, ge=0, le=1)
    min_margin: float = Field(default=0.10, ge=0, le=1)
    config_version: str = Field(default="fusion-thresholds-demo-v1", min_length=1, max_length=128)

    def thresholds(self) -> FusionThresholds:
        return FusionThresholds(
            matched_score=self.matched_score,
            unknown_score=self.unknown_score,
            min_margin=self.min_margin,
            config_version=self.config_version,
        )


class ChannelEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["ocr", "barcode", "packaging", "metadata"]
    support: list[str] = Field(default_factory=list)
    conflict: list[str] = Field(default_factory=list)
    missing: bool = False
    score: float = Field(ge=0, le=1)
    versions: list[str] = Field(default_factory=list)


class FusedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    rank: int = Field(ge=1)
    score: float = Field(ge=0, le=1)
    channel_evidence: dict[str, ChannelEvidence]
    evidence_ids: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    supported_channels: int = Field(ge=0, le=4)
    versions: dict[str, str]


class CandidateFusionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    status: FusionStatus
    candidates: list[FusedCandidate] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    selected_score: float | None = Field(default=None, ge=0, le=1)
    score_margin: float | None = Field(default=None, ge=0, le=1)
    thresholds: FusionThresholds
    weights: FusionWeights
    reasons: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    versions: dict[str, str]
    requires_human_confirmation: Literal[True] = True
    health_event_allowed: Literal[False] = False


class CalibrationSample(BaseModel):
    """A scored, frozen-set sample used to calibrate decision thresholds."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(min_length=1, max_length=128)
    top_score: float = Field(ge=0, le=1)
    score_margin: float = Field(ge=0, le=1)
    expected_status: FusionStatus
    predicted_candidate_id: str | None = None
    expected_candidate_id: str | None = None
    observed_conflict: bool = False
    observed_unknown: bool = False
    observed_review: bool = False


class CalibrationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    correct_matches: int = Field(ge=0)
    false_matches: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    acceptance_rate: float = Field(ge=0, le=1)
    false_match_rate: float = Field(ge=0, le=1)
    rejection_rate: float = Field(ge=0, le=1)
    coverage: float = Field(ge=0, le=1)


class CalibrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CALIBRATION_SCHEMA_VERSION
    thresholds: FusionThresholds
    validation: CalibrationMetrics
    independent_test: CalibrationMetrics
    sample_sha256: str
    limitations: list[str] = Field(default_factory=list)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _field_values(result: EvidencePipelineResult, field_name: str) -> list[Any]:
    return [field for field in result.fields if field.field_name == field_name]


def _field_evidence_ids(result: EvidencePipelineResult, field_name: str) -> list[str]:
    return [
        evidence_id
        for field in _field_values(result, field_name)
        for evidence_id in field.evidence_ids
    ]


def _versions(result: EvidencePipelineResult, record: MasterDataRecord) -> dict[str, str]:
    versions = {key: str(value) for key, value in result.versions.items()}
    versions["fusion_rule_version"] = RULE_VERSION
    versions["master_record_id"] = record.record_id
    return versions


def _channel(
    channel: Literal["ocr", "barcode", "packaging", "metadata"],
    *,
    support: list[str],
    conflict: list[str],
    score: float,
    versions: list[str],
) -> ChannelEvidence:
    return ChannelEvidence(
        channel=channel,
        support=support,
        conflict=conflict,
        missing=not support and not conflict,
        score=max(0.0, min(1.0, score)),
        versions=sorted({version for version in versions if version}),
    )


def _candidate_channels(
    result: EvidencePipelineResult,
    record: MasterDataRecord,
    reasons: list[str],
) -> tuple[dict[str, ChannelEvidence], list[str]]:
    conflicts: list[str] = []
    evidence_by_id = {item.id: item for item in result.evidence}
    name_fields = _field_values(result, "drug_name")
    aliases = {_normalize(alias) for alias in record.name_aliases}
    name_values = {_normalize(field.normalized_value) for field in name_fields}
    if "NAME_EXACT" in reasons:
        name_confidences = [
            min(
                field.confidence,
                *(
                    evidence_by_id[evidence_id].confidence
                    for evidence_id in field.evidence_ids
                    if evidence_id in evidence_by_id
                ),
            )
            for field in name_fields
        ]
        ocr = _channel(
            "ocr",
            support=_field_evidence_ids(result, "drug_name") or ["master:NAME_EXACT"],
            conflict=[],
            score=max(name_confidences, default=0.0),
            versions=[field.parser_version for field in name_fields]
            + [field.model_version for field in name_fields],
        )
    elif name_values and aliases.isdisjoint(name_values):
        ocr = _channel(
            "ocr",
            support=[],
            conflict=["drug_name does not match master aliases"],
            score=0.0,
            versions=[field.parser_version for field in name_fields]
            + [field.model_version for field in name_fields],
        )
        conflicts.append("OCR_NAME_MASTER_CONFLICT")
    else:
        ocr = _channel("ocr", support=[], conflict=[], score=0.0, versions=[])

    valid_barcodes = {
        barcode.normalized_value
        for barcode in result.barcodes
        if barcode.validation_status == "VALID"
    }
    barcode_versions = [barcode.decoder_version for barcode in result.barcodes]
    if record.product_barcode and record.product_barcode in valid_barcodes:
        matching_barcodes = [
            barcode_item
            for barcode_item in result.barcodes
            if barcode_item.validation_status == "VALID"
            and barcode_item.normalized_value == record.product_barcode
        ]
        barcode = _channel(
            "barcode",
            support=[
                barcode_item.evidence_id
                for barcode_item in result.barcodes
                if barcode_item.validation_status == "VALID"
                and barcode_item.normalized_value == record.product_barcode
            ],
            conflict=[],
            score=max(
                (barcode_item.confidence for barcode_item in matching_barcodes),
                default=0.0,
            ),
            versions=barcode_versions,
        )
    elif valid_barcodes and record.product_barcode:
        barcode = _channel(
            "barcode",
            support=[],
            conflict=["valid barcode does not match this master record"],
            score=0.0,
            versions=barcode_versions,
        )
        conflicts.append("BARCODE_MASTER_CONFLICT")
    else:
        barcode = _channel("barcode", support=[], conflict=[], score=0.0, versions=barcode_versions)

    packaging_fields = _field_values(result, "packaging_type")
    packaging_values = {_normalize(field.normalized_value) for field in packaging_fields}
    master_packaging = _normalize(record.packaging_type) if record.packaging_type else None
    if packaging_values and master_packaging:
        if master_packaging in packaging_values:
            packaging_confidences = [
                min(
                    field.confidence,
                    *(
                        evidence_by_id[evidence_id].confidence
                        for evidence_id in field.evidence_ids
                        if evidence_id in evidence_by_id
                    ),
                )
                for field in packaging_fields
                if _normalize(field.normalized_value) == master_packaging
            ]
            packaging = _channel(
                "packaging",
                support=_field_evidence_ids(result, "packaging_type"),
                conflict=[],
                score=max(packaging_confidences, default=0.0),
                versions=[field.parser_version for field in packaging_fields],
            )
        else:
            packaging = _channel(
                "packaging",
                support=[],
                conflict=["packaging type does not match master record"],
                score=0.0,
                versions=[field.parser_version for field in packaging_fields],
            )
            conflicts.append("PACKAGING_MASTER_CONFLICT")
    else:
        packaging = _channel("packaging", support=[], conflict=[], score=0.0, versions=[])

    metadata_fields = [
        *_field_values(result, "specification"),
        *_field_values(result, "manufacturer"),
    ]
    metadata_support: list[str] = []
    metadata_conflict: list[str] = []
    metadata_matches = 0
    metadata_confidence_sum = 0.0
    metadata_comparisons = 0
    for field in metadata_fields:
        expected = (
            record.specification
            if field.field_name == "specification"
            else record.manufacturer
        )
        if not expected:
            continue
        metadata_comparisons += 1
        if _normalize(field.normalized_value) == _normalize(expected):
            metadata_matches += 1
            metadata_support.extend(field.evidence_ids)
            metadata_confidence_sum += min(
                field.confidence,
                *(
                    evidence_by_id[evidence_id].confidence
                    for evidence_id in field.evidence_ids
                    if evidence_id in evidence_by_id
                ),
            )
        else:
            metadata_conflict.append(f"{field.field_name} does not match master record")
    if metadata_conflict:
        conflicts.append("METADATA_MASTER_CONFLICT")
    metadata = _channel(
        "metadata",
        support=metadata_support,
        conflict=metadata_conflict,
        score=(
            metadata_confidence_sum / metadata_comparisons
            if metadata_comparisons
            else 0.0
        ),
        versions=[field.parser_version for field in metadata_fields],
    )
    return {
        "ocr": ocr,
        "barcode": barcode,
        "packaging": packaging,
        "metadata": metadata,
    }, conflicts


def _status_from_scores(
    top_score: float,
    margin: float,
    *,
    thresholds: FusionThresholds,
    supported_channels: int,
    conflict: bool = False,
    unknown: bool = False,
    review: bool = False,
) -> FusionStatus:
    if conflict:
        return FusionStatus.CONFLICT
    if unknown or top_score < thresholds.unknown_score:
        return FusionStatus.UNKNOWN
    if (
        not review
        and supported_channels >= 2
        and top_score >= thresholds.matched_score
        and margin >= thresholds.min_margin
    ):
        return FusionStatus.MATCHED
    return FusionStatus.REVIEW


def _next_steps(status: FusionStatus) -> list[str]:
    return {
        FusionStatus.MATCHED: ["人工确认候选后，才允许进入健康事件流程。"],
        FusionStatus.CONFLICT: ["核对冲突的 OCR、条码、包装或主数据证据。", "人工选择或修正候选。"],
        FusionStatus.UNKNOWN: [
            "补拍清晰图片或补充条码、字段证据。",
            "未知结果不得创建药品健康事实。",
        ],
        FusionStatus.REVIEW: ["补充缺失证据或重新处理。", "进入人工复核，不自动确认身份。"],
    }[status]


def fuse_evidence(
    result: EvidencePipelineResult,
    master_data: LocalMasterData,
    *,
    weights: FusionWeights | None = None,
    thresholds: FusionThresholds | None = None,
) -> CandidateFusionResult:
    """Rank existing master candidates and return a safe four-state result."""
    weights = weights or FusionWeights()
    thresholds = thresholds or FusionThresholds()
    records = {record.record_id: record for record in master_data.records}
    fused: list[FusedCandidate] = []
    for candidate in result.master_candidates:
        record = records.get(candidate.record_id)
        if record is None:
            continue
        channels, conflicts = _candidate_channels(result, record, candidate.reasons)
        score = sum(
            weight * channels[channel].score
            for channel, weight in (
                ("ocr", weights.ocr),
                ("barcode", weights.barcode),
                ("packaging", weights.packaging),
                ("metadata", weights.metadata),
            )
        )
        evidence_ids = sorted(
            {
                evidence_id
                for channel in channels.values()
                for evidence_id in [*channel.support, *channel.conflict]
                if evidence_id and not evidence_id.startswith("master:")
            }
        )
        fused.append(
            FusedCandidate(
                candidate_id=record.record_id,
                rank=1,
                score=round(score, 6),
                channel_evidence=channels,
                evidence_ids=evidence_ids,
                conflicts=sorted(set(conflicts)),
                supported_channels=sum(not channel.missing for channel in channels.values()),
                versions=_versions(result, record),
            )
        )
    fused.sort(key=lambda item: (-item.score, item.candidate_id))
    for rank, candidate in enumerate(fused, start=1):
        candidate.rank = rank

    top = fused[0] if fused else None
    second_score = fused[1].score if len(fused) > 1 else 0.0
    margin = round(top.score - second_score, 6) if top else None
    finding_codes = {finding.code for finding in result.findings}
    # A losing candidate may legitimately conflict with the observed evidence;
    # that must not hide a clear top candidate.  Only conflicts on the selected
    # candidate (or upstream channel conflict) change the overall state.
    conflict = result.fusion_readiness == "CONFLICT" or bool(top and top.conflicts)
    review = result.fusion_readiness == "REVIEW" or any(
        finding.severity == "REVIEW" for finding in result.findings
    )
    status = _status_from_scores(
        top.score if top else 0.0,
        margin if margin is not None else 0.0,
        thresholds=thresholds,
        supported_channels=top.supported_channels if top else 0,
        conflict=conflict,
        unknown=not fused,
        review=review,
    )
    reasons = sorted(finding_codes)
    if not fused:
        reasons.append("NO_MASTER_CANDIDATE")
    elif top is not None:
        if top.supported_channels < 2:
            reasons.append("SINGLE_CHANNEL_EVIDENCE")
        if top.score < thresholds.unknown_score:
            reasons.append("FUSION_SCORE_BELOW_UNKNOWN_THRESHOLD")
        elif top.score < thresholds.matched_score:
            reasons.append("FUSION_SCORE_BELOW_MATCH_THRESHOLD")
        if margin is not None and margin < thresholds.min_margin:
            reasons.append("CANDIDATE_MARGIN_TOO_SMALL")
    if conflict:
        reasons.append("EVIDENCE_CONFLICT")
    reasons = sorted(set(reasons))
    return CandidateFusionResult(
        status=status,
        candidates=fused,
        selected_candidate_id=top.candidate_id if top else None,
        selected_score=top.score if top else None,
        score_margin=margin,
        thresholds=thresholds,
        weights=weights,
        reasons=reasons,
        next_steps=_next_steps(status),
        versions={
            **{key: str(value) for key, value in result.versions.items()},
            "fusion_rule_version": RULE_VERSION,
            "fusion_weights_version": weights.version,
            "fusion_threshold_version": thresholds.config_version,
            "master_data_version": master_data.version,
        },
    )


def _predict_sample(sample: CalibrationSample, thresholds: FusionThresholds) -> FusionStatus:
    return _status_from_scores(
        sample.top_score,
        sample.score_margin,
        thresholds=thresholds,
        supported_channels=2,
        conflict=sample.observed_conflict,
        unknown=sample.observed_unknown,
        review=sample.observed_review,
    )


def _metrics(samples: list[CalibrationSample], thresholds: FusionThresholds) -> CalibrationMetrics:
    accepted = correct = false_matches = 0
    for sample in samples:
        predicted = _predict_sample(sample, thresholds)
        if predicted == FusionStatus.MATCHED:
            accepted += 1
            if (
                sample.expected_status == FusionStatus.MATCHED
                and sample.predicted_candidate_id is not None
                and sample.predicted_candidate_id == sample.expected_candidate_id
            ):
                correct += 1
            else:
                false_matches += 1
    total = len(samples)
    rejected = total - accepted
    return CalibrationMetrics(
        sample_count=total,
        accepted_count=accepted,
        correct_matches=correct,
        false_matches=false_matches,
        rejected_count=rejected,
        acceptance_rate=correct / total if total else 0.0,
        false_match_rate=false_matches / accepted if accepted else 0.0,
        rejection_rate=rejected / total if total else 0.0,
        coverage=accepted / total if total else 0.0,
    )


def calibrate_thresholds(
    validation: list[CalibrationSample],
    independent_test: list[CalibrationSample],
    *,
    config_version: str = "fusion-thresholds-calibrated-v1",
) -> CalibrationReport:
    """Scan deterministic threshold candidates on validation and report test metrics."""
    if not validation or not independent_test:
        raise ValueError("FUSION_CALIBRATION_SPLITS_REQUIRED")
    best: tuple[tuple[Any, ...], FusionThresholds, CalibrationMetrics] | None = None
    for matched_score_i in range(50, 96, 5):
        for unknown_score_i in range(10, 50, 5):
            for margin_i in range(0, 41, 5):
                matched_score = matched_score_i / 100
                unknown_score = unknown_score_i / 100
                if unknown_score >= matched_score:
                    continue
                thresholds = FusionThresholds(
                    matched_score=matched_score,
                    unknown_score=unknown_score,
                    min_margin=margin_i / 100,
                    config_version=config_version,
                )
                metrics = _metrics(validation, thresholds)
                key = (
                    metrics.false_matches,
                    -metrics.correct_matches,
                    -metrics.coverage,
                    matched_score,
                    thresholds.min_margin,
                    unknown_score,
                )
                if best is None or key < best[0]:
                    best = (key, thresholds, metrics)
    assert best is not None
    thresholds = best[1]
    all_samples = [sample.model_dump(mode="json") for sample in [*validation, *independent_test]]
    canonical = json.dumps(
        all_samples, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return CalibrationReport(
        thresholds=thresholds,
        validation=best[2],
        independent_test=_metrics(independent_test, thresholds),
        sample_sha256=hashlib.sha256(canonical).hexdigest(),
        limitations=[
            (
                "Calibration is only valid for frozen, approved validation and independent "
                "test splits."
            ),
            "A calibrated MATCHED result still requires human confirmation before a health event.",
            "Synthetic or unapproved medicine data must not be presented as production accuracy.",
        ],
    )
