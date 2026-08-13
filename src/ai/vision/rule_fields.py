"""Deterministic rule/dictionary field candidates for the OCR-first chain.

The HCT-201 contract orders the chain as "rules, unit/date/batch formats and
the local dictionary generate field candidates; the local LLM only
classifies existing candidates".  This module is that rule layer: it scans
real OCR lines with fixed patterns and emits ``FieldProposal`` objects, so
the loop produces structured candidates even when the LLM is unavailable.

Because the evidence pipeline only accepts a proposal whose normalized value
exactly equals a referenced token's normalized value, line-level OCR output
(e.g. ``LOT A12345 EXP 2027-05``) is refined into sub-tokens: verbatim
substrings of the parent line that keep the parent's region, confidence and
engine version.  Nothing is invented — every sub-token value is asserted to
be a literal substring of the parent OCR text.

Confidences are deterministic system rules, not model self-reports:
marker-anchored extractions inherit the parent OCR confidence; the drug-name
heuristic is fixed at a low confidence because it has no dictionary support.
"""

from __future__ import annotations

import re

from ai.vision.evidence_pipeline import (
    BarcodeCandidate,
    FieldProposal,
    OCRToken,
    PackageRegionProposal,
)

PARSER_VERSION = "rule-fields-v1"
NAME_HEURISTIC_CONFIDENCE = 0.5
MAX_NAME_CANDIDATES = 2

EXPIRY_MARK = re.compile(r"有效期至?|失效日?期?|EXP(?:IRY)?(?:\s*DATE)?", re.IGNORECASE)
PRODUCTION_MARK = re.compile(r"生产日期|MFG|MFD", re.IGNORECASE)
DATE_PATTERN = re.compile(
    r"20\d{2}\s*[年./-]\s*\d{1,2}(?:\s*[月./-]\s*\d{1,2}\s*日?|月)?"
)
BATCH_PATTERN = re.compile(
    r"(?:批\s*号|LOT(?:\s*NO\.?)?|BATCH)[:：#\s]*([A-Z0-9][A-Z0-9-]{2,19})",
    re.IGNORECASE,
)
SPEC_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mg|g|ml|μg|ug|iu)\s*[x×*]\s*\d+(?:\s*(?:片|粒|袋|支|丸|贴|枚))?",
    re.IGNORECASE,
)
MANUFACTURER_MARK = re.compile(
    r"制药|药业|生物制品|Pharmaceutical|Pharma\b", re.IGNORECASE
)
CJK_OR_LETTER = re.compile(r"[\u4e00-\u9fff A-Za-z]")


def _digit_ratio(value: str) -> float:
    stripped = value.replace(" ", "")
    if not stripped:
        return 0.0
    return sum(ch.isdigit() for ch in stripped) / len(stripped)


class _Collector:
    """Accumulates proposals plus the sub-tokens they reference."""

    def __init__(self) -> None:
        self.subtokens: list[OCRToken] = []
        self.proposals: list[FieldProposal] = []
        self._seen: set[tuple[str, str]] = set()

    def propose(
        self,
        field_name: str,
        value: str,
        parent: OCRToken,
        *,
        confidence: float,
    ) -> None:
        value = value.strip()
        key = (field_name, value)
        if not value or key in self._seen:
            return
        # verbatim guarantee: rules only quote, never rewrite
        if value not in parent.raw_value:
            raise AssertionError(
                f"rule value must be a literal substring: {value!r}"
            )
        if value == parent.raw_value.strip():
            evidence_id = parent.id
        else:
            evidence_id = f"{parent.id}-f{len(self.subtokens) + 1}"
            self.subtokens.append(
                OCRToken(
                    id=evidence_id,
                    raw_value=value,
                    region=parent.region,
                    confidence=parent.confidence,
                    engine_version=parent.engine_version,
                    language=parent.language,
                )
            )
        self._seen.add(key)
        self.proposals.append(
            FieldProposal(
                field_name=field_name,  # type: ignore[arg-type]
                raw_value=value,
                evidence_ids=[evidence_id],
                confidence=min(max(confidence, 0.0), 1.0),
                parser_version=PARSER_VERSION,
                source="rule",
            )
        )


def propose_fields(
    ocr_tokens: list[OCRToken],
    barcodes: list[BarcodeCandidate] | None = None,
    package_regions: list[PackageRegionProposal] | None = None,
) -> tuple[list[OCRToken], list[FieldProposal]]:
    """Return ``(extra_subtokens, proposals)`` derived from existing evidence.

    The caller appends the sub-tokens to its OCR token list before building
    the evidence request, so every proposal reference resolves server-side.
    """
    collector = _Collector()
    name_candidates: list[OCRToken] = []

    for token in ocr_tokens:
        text = token.raw_value
        consumed = False

        batch_match = BATCH_PATTERN.search(text)
        if batch_match:
            collector.propose(
                "batch_number", batch_match.group(1), token,
                confidence=token.confidence,
            )
            consumed = True

        date_match = DATE_PATTERN.search(text)
        if date_match and not PRODUCTION_MARK.search(text):
            entire_token_is_date = date_match.group(0).strip() == text.strip()
            if EXPIRY_MARK.search(text) or entire_token_is_date:
                collector.propose(
                    "expiry_date", date_match.group(0), token,
                    confidence=token.confidence,
                )
                consumed = True

        spec_match = SPEC_PATTERN.search(text)
        if spec_match:
            collector.propose(
                "specification", spec_match.group(0), token,
                confidence=token.confidence,
            )
            consumed = True

        if MANUFACTURER_MARK.search(text) and len(text.strip()) <= 40:
            collector.propose(
                "manufacturer", text.strip(), token, confidence=token.confidence
            )
            consumed = True

        if (
            not consumed
            and 2 <= len(text.strip()) <= 40
            and CJK_OR_LETTER.search(text)
            and _digit_ratio(text) < 0.3
            and not EXPIRY_MARK.search(text)
            and not PRODUCTION_MARK.search(text)
        ):
            name_candidates.append(token)

    for token in sorted(name_candidates, key=lambda t: -t.confidence)[
        :MAX_NAME_CANDIDATES
    ]:
        collector.propose(
            "drug_name", token.raw_value.strip(), token,
            confidence=NAME_HEURISTIC_CONFIDENCE,
        )

    for barcode in barcodes or []:
        if not barcode.decode_valid:
            continue
        collector.proposals.append(
            FieldProposal(
                field_name="product_barcode",
                raw_value=barcode.raw_value,
                evidence_ids=[barcode.id],
                confidence=barcode.confidence,
                parser_version=PARSER_VERSION,
                source="rule",
            )
        )

    seen_labels: set[str] = set()
    for region in package_regions or []:
        if region.label in seen_labels:
            continue
        seen_labels.add(region.label)
        collector.proposals.append(
            FieldProposal(
                field_name="packaging_type",
                raw_value=region.label,
                evidence_ids=[region.id],
                confidence=region.confidence,
                parser_version=PARSER_VERSION,
                source="rule",
            )
        )

    return collector.subtokens, collector.proposals
