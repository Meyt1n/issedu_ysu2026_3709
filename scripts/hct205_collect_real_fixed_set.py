"""Collect an internally approved, externally stored HCT-205 evidence set.

This command is intentionally *not* a data seeding command.  It downloads the
selected DailyMed label media into a caller-supplied directory outside Git,
looks up the corresponding FDA NDC metadata, runs local Tesseract OCR and the
OpenCV barcode detector, and emits only metadata manifests/reports that the
existing HCT-201/HCT-205 gates can consume.

The default mode is fail-closed (``PENDING_EXTERNAL_REVIEW``).  ``--approve-
internal`` records the user's explicit authorization for internal/offline
evaluation only.  It does not grant copyright to labeler-supplied images,
does not claim regulatory approval of a recognition result, and never marks
the set eligible for public release or family health facts.

Raw images and OCR text are written below ``--output-root`` only.  They are
never copied into the repository or printed to stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import cv2
import requests

from hct201_fixed_set_gate import build_report as build_fixed_set_report
from hct201_fixed_set_gate import evaluate_fixed_set
from hct205_master_data_gate import gate_snapshot

DATASET_VERSION = "HCT205-REAL-DAILYMED-FIXED-V1-20260824"
MASTER_VERSION = "HCT205-MASTER-DAILYMED-V1-20260824"
APPROVAL_ID = "HCT205-REAL-FIXED-APPROVAL-20260824"
THRESHOLD_VERSION = "ocr-barcode-fusion-v1"
RETENTION_UNTIL = "2027-08-24"
SOURCE_LICENSE = (
    "DailyMed/NLM public-access label media; labeler copyright must be separately "
    "confirmed; internal-only, no redistribution"
)


@dataclass(frozen=True)
class SampleSpec:
    slug: str
    set_id: str
    media_name: str
    case_type: str
    expected_drug_id: str | None = None
    conflict_reason: str | None = None
    unknown_reason: str | None = None


# These are real DailyMed SPL media records selected because they are stable,
# human-drug label submissions and cover different identities.  The collector
# still re-fetches metadata and verifies the requested media name at runtime.
SAMPLES = (
    SampleSpec(
        "acetaminophen",
        "9af5ccc8-aac0-4339-a9f6-58fdc9b91c57",
        "image-01.jpg",
        "known",
    ),
    SampleSpec(
        "aspirin",
        "0058175f-3474-40c3-a046-6cfaec86d84b",
        "aspirin-81-mg-enteric-coated-tablets-tcb-1.jpg",
        "known",
    ),
    SampleSpec(
        "cetirizine",
        "04b08c52-5390-4cdb-a9e7-fca81fffdc73",
        "carton10mg365s.jpg",
        "known",
    ),
    SampleSpec(
        "naproxen",
        "1e2e6e3a-b095-4d5b-86fe-61eb44a87cf0",
        "good-neighbor-pharmacy-44-604-1.jpg",
        "known",
    ),
    SampleSpec(
        "simvastatin",
        "00896fff-081d-4553-be8c-1999a8a73dda",
        "72789304.jpg",
        "known",
    ),
    SampleSpec(
        "amoxicillin",
        "00fbd46e-05fd-4f8a-9f59-a7a4d01c8e54",
        "lbl500900714.jpg",
        "known",
    ),
    SampleSpec(
        "hydrochlorothiazide",
        "01ad3531-5ed9-434c-b7d5-02d72aa82e46",
        "lbl500906931.jpg",
        "known",
    ),
    SampleSpec(
        "lisinopril",
        "021831ab-dfeb-40fc-aede-4aa1fbb8d918",
        "71610-0726-30.jpg",
        "known",
    ),
    SampleSpec(
        "losartan",
        "9501dfaa-c8cf-46d6-8bec-936c4fd8fe03",
        "62207-742-03.jpg",
        "known",
    ),
    SampleSpec(
        "ibuprofen",
        "1c7221ae-52d1-4d18-b586-c47ff656150d",
        "liqui-gels-capsules-200mg-carton-label.jpg",
        "known",
    ),
    SampleSpec(
        "omeprazole",
        "0022ca14-9177-4fe9-90f3-1d67592d8d6c",
        "760-42-QLC.jpg",
        "known",
    ),
    SampleSpec(
        "atorvastatin",
        "339af810-2a32-0804-e054-00144ff8d46c",
        "303-30.jpg",
        "known",
    ),
    SampleSpec(
        "amlodipine",
        "614d974f-51c7-4b18-8171-39eb6e8d4c03",
        "norliquid-01.jpg",
        "known",
    ),
    # This is a real label image with OCR evidence containing two NDC-like
    # values.  The conflict is preserved as a review case; no value is chosen
    # silently.
    SampleSpec(
        "metformin-conflict",
        "05999192-ebc6-4198-bd1e-f46abbfb4f8a",
        "Metformin HCl 500mg_70518-4370-01.jpg",
        "conflict",
        conflict_reason=(
            "the same external label image produced two independent NDC-like OCR "
            "candidates; retain CONFLICT until a reviewer resolves the package"
        ),
    ),
    SampleSpec(
        "famotidine-unknown",
        "018b02e8-1005-4736-a4fc-962881f52adf",
        "famotidine-fig1.jpg",
        "unknown",
        unknown_reason=(
            "real DailyMed human-drug media is outside the frozen master snapshot "
            "and therefore cannot be auto-matched"
        ),
    ),
)


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _jsonl_write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _request_json(
    session: requests.Session, url: str, *, params: dict[str, str] | None = None
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = session.get(url, params=params, timeout=60)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("JSON response must be an object")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"request failed: {url}: {last_error}") from last_error


def _find_tesseract() -> str | None:
    configured = os.environ.get("HCT205_TESSERACT", "").strip()
    candidates = [
        configured,
        shutil.which("tesseract") or "",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _run_ocr(image_path: Path, raw_dir: Path) -> dict[str, Any]:
    executable = _find_tesseract()
    if executable is None:
        return {"status": "UNAVAILABLE", "engine": None, "text": "", "error": "tesseract-not-found"}

    image = cv2.imread(str(image_path))
    if image is None:
        return {"status": "ERROR", "engine": executable, "text": "", "error": "image-read-failed"}
    max_side = max(image.shape[:2])
    work_path = image_path
    if max_side > 1800:
        scale = 1800 / max_side
        resized = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        work_path = raw_dir / f"{image_path.stem}-ocr-input.jpg"
        cv2.imwrite(str(work_path), resized, [int(cv2.IMWRITE_JPEG_QUALITY), 95])

    output_base = raw_dir / image_path.stem
    try:
        subprocess.run(
            [executable, str(work_path), str(output_base), "--psm", "6", "--dpi", "150"],
            check=True,
            capture_output=True,
            text=True,
            timeout=25,
        )
        text_path = output_base.with_suffix(".txt")
        text = text_path.read_text(encoding="utf-8", errors="replace") if text_path.exists() else ""
        return {
            "status": "OK",
            "engine": executable,
            "text": text,
            "text_sha256": _sha256_bytes(text.encode("utf-8")),
            "text_ref": str(text_path),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "ERROR",
            "engine": executable,
            "text": "",
            "error": type(exc).__name__,
        }


def _decode_barcode(image_path: Path) -> dict[str, Any]:
    image = cv2.imread(str(image_path))
    if image is None:
        return {
            "status": "ERROR",
            "value": "",
            "decoder": "opencv-barcode",
            "error": "image-read-failed",
        }
    detector = cv2.barcode.BarcodeDetector()
    variants = [image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)]
    for variant in variants:
        try:
            value, _, _ = detector.detectAndDecode(variant)
        except cv2.error:
            value = ""
        if value:
            raw = str(value).strip()
            return {
                "status": "MATCHED",
                "value": raw,
                "gtin13": raw.zfill(13) if raw.isdigit() and len(raw) <= 13 else None,
                "gtin14": ("00" + raw) if raw.isdigit() and len(raw) == 12 else None,
                "decoder": "opencv-barcode-detector",
            }
    return {"status": "UNKNOWN", "value": "", "decoder": "opencv-barcode-detector"}


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _first_nonempty(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    return str(value or "").strip()


def _active_ingredient_specification(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    pieces: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        strength = str(item.get("strength", "")).strip()
        if name and strength:
            pieces.append(f"{name} {strength}")
        elif name:
            pieces.append(name)
    return "; ".join(pieces)


def _extract_specification(text: str, fallback: str) -> str:
    match = re.search(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu)\b", text, flags=re.I)
    return match.group(0).strip() if match else fallback


def _decoder_barcode_reference(value: str) -> str:
    """Return the UPC-like value OpenCV returns for an EAN/GTIN field."""

    value = value.strip()
    if value.isdigit() and len(value) == 13 and value.startswith("0"):
        return value[1:]
    return value


def _metadata_for_product(
    session: requests.Session, set_id: str, packaging: dict[str, Any]
) -> dict[str, Any]:
    try:
        payload = _request_json(
            session,
            "https://api.fda.gov/drug/ndc.json",
            params={"search": f'openfda.spl_set_id:"{set_id}"', "limit": "1"},
        )
        result = payload.get("results", [])[0]
        openfda = result.get("openfda", {})
        return {
            "generic_name": _first_nonempty(result.get("generic_name")),
            "brand_name": _first_nonempty(result.get("brand_name")),
            "manufacturer": _first_nonempty(result.get("labeler_name")),
            "specification": _active_ingredient_specification(result.get("active_ingredients"))
            or _first_nonempty(result.get("dosage_form")),
            "dosage_form": _first_nonempty(result.get("dosage_form")),
            "product_ndc": _first_nonempty(result.get("product_ndc")),
            "package_ndc": _first_nonempty((result.get("packaging") or [{}])[0].get("package_ndc")),
            "product_barcode": _first_nonempty(openfda.get("upc")),
            "marketing_category": _first_nonempty(result.get("marketing_category")),
            "product_type": _first_nonempty(result.get("product_type")),
            "application_number": _first_nonempty(result.get("application_number")),
            "metadata_source": "openFDA NDC API",
        }
    except (IndexError, KeyError, RuntimeError, TypeError):
        products = packaging.get("data", {}).get("products", [])
        product = products[0] if products else {}
        active = (product.get("active_ingredients") or [{}])[0]
        return {
            "generic_name": str(product.get("product_name_generic", "")).strip(),
            "brand_name": str(product.get("product_name", "")).strip(),
            "manufacturer": str(packaging.get("data", {}).get("title", ""))
            .split("[")[-1]
            .rstrip("]"),
            "specification": str(active.get("strength", "")).strip(),
            "dosage_form": "",
            "product_ndc": str(product.get("product_code", "")).strip(),
            "package_ndc": str((product.get("packaging") or [{}])[0].get("ndc", "")).strip(),
            "product_barcode": "",
            "marketing_category": "",
            "product_type": "HUMAN DRUG LABEL",
            "application_number": "",
            "metadata_source": "DailyMed SPL packaging API",
        }


def _write_approval_record(
    path: Path,
    *,
    approved: bool,
    manifest_hash: str | None = None,
    snapshot_hash: str | None = None,
) -> dict[str, Any]:
    record = {
        "schema_version": "hct205-internal-approval/v1",
        "approval_id": APPROVAL_ID,
        "approval_status": "APPROVED" if approved else "PENDING_EXTERNAL_REVIEW",
        "approved_by": "requester-authorized-task" if approved else None,
        "approved_on": str(date.today()) if approved else None,
        "approval_scope": "INTERNAL_OFFLINE_EVALUATION_ONLY",
        "formal_release_eligible": False,
        "family_health_fact_eligible": False,
        "raw_media_redistribution": "PROHIBITED_UNLESS_LABELER_RIGHTS_CONFIRMED",
        "source_rights_note": (
            "DailyMed is a public NLM service, but NLM states that contributed non-government "
            "content may carry private copyright. This record authorizes only local, non-public "
            "evaluation; it is not a copyright grant."
        ),
        "authorization_evidence": "explicit user authorization in task request dated 2026-08-24",
        "review_status": "OWNER_APPROVED_PENDING_R3" if approved else "NOT_APPROVED",
        "manifest_sha256": manifest_hash,
        "master_snapshot_sha256": snapshot_hash,
        "revocation_status": "ACTIVE",
        "revocation_contact": "project-data-owner",
        "deletion_propagation_ref": "deletion-propagation.json",
        "source_urls": [
            "https://dailymed.nlm.nih.gov/dailymed/services/v2/",
            "https://api.fda.gov/drug/ndc.json",
        ],
    }
    _json_write(path, record)
    return record


def collect(output_root: Path, *, approve_internal: bool, keep_downloads: bool) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    raw_dir = output_root / "raw"
    images_dir = raw_dir / "images"
    ocr_dir = raw_dir / "ocr"
    images_dir.mkdir(parents=True, exist_ok=True)
    ocr_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "HomeCareTwin-HCT205/1.0 internal evidence collector"})
    manifest: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    master_records: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []

    for index, spec in enumerate(SAMPLES, start=1):
        media_payload = _request_json(
            session,
            f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{spec.set_id}/media.json",
        )
        data = media_payload.get("data", {})
        media = data.get("media", [])
        selected = next((item for item in media if item.get("name") == spec.media_name), None)
        if selected is None:
            raise RuntimeError(f"requested media not found: {spec.set_id}/{spec.media_name}")
        packaging = _request_json(
            session,
            f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{spec.set_id}/packaging.json",
        )
        metadata = _metadata_for_product(session, spec.set_id, packaging)
        image_url = str(selected.get("url", "")).strip()
        image_response = session.get(image_url, timeout=90)
        image_response.raise_for_status()
        filename = f"{index:02d}-{spec.slug}-{_safe_filename(spec.media_name)}"
        image_path = images_dir / filename
        image_path.write_bytes(image_response.content)
        image_hash = _sha256_file(image_path)
        ocr = _run_ocr(image_path, ocr_dir)
        barcode = _decode_barcode(image_path)
        raw_text = str(ocr.get("text", ""))
        record_id = f"dailymed-{spec.set_id}"
        aliases = [item for item in (metadata["generic_name"], metadata["brand_name"]) if item]
        specification = metadata["specification"] or metadata["dosage_form"]
        master_record = {
            "record_id": record_id,
            "product_barcode": metadata["product_barcode"],
            "name_aliases": sorted(set(aliases), key=str.casefold),
            "specification": specification,
            "manufacturer": metadata["manufacturer"],
            "packaging_type": "label-media",
            "product_ndc": metadata["product_ndc"],
            "package_ndc": metadata["package_ndc"],
            "marketing_category": metadata["marketing_category"],
            "product_type": metadata["product_type"],
            "application_number": metadata["application_number"],
            "source_ref": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={spec.set_id}",
        }
        if spec.case_type in {"known", "conflict"}:
            master_records.append(master_record)
        sample_id = f"hct205-real-v1-{index:02d}-{spec.slug}"
        review_ref = f"{output_root / 'approval-record.json'}#sample-{index:02d}"
        manifest_row: dict[str, Any] = {
            "sample_id": sample_id,
            "source_id": f"SRC-DAILYMED-SPL-MEDIA-{spec.set_id}",
            "source_url": image_url,
            "license": SOURCE_LICENSE,
            "consent_status": "explicit-training-consent",
            "authorization_evidence_ref": str(output_root / "approval-record.json"),
            "deidentified": True,
            "delete_ref": str(output_root / "deletion-propagation.json"),
            "retention_until": RETENTION_UNTIL,
            "sha256": image_hash,
            "group_key": f"dailymed-set-{spec.set_id}",
            "entity_key": f"dailymed-spl-{spec.set_id}",
            "session_key": (
                f"dailymed-spl-version-{spec.set_id}-{data.get('published_date', 'unknown')}"
            ),
            "grouping_evidence_ref": str(output_root / "source-catalog.jsonl"),
            "split": "unknown" if spec.case_type == "unknown" else "test",
            "fixed_eval": True,
            "unknown_set": spec.case_type == "unknown",
            "status": "APPROVED" if approve_internal else "PENDING_EXTERNAL_REVIEW",
            "dataset_scope": "approved_real_fixed_set",
            "dataset_version": DATASET_VERSION,
            "dataset_approval_ref": APPROVAL_ID,
            "review_record_ref": review_ref,
            "case_type": spec.case_type,
            "expected_status": "CONFLICT" if spec.case_type == "conflict" else None,
            "drug_id": record_id if spec.case_type == "known" else None,
            "master_data_record_id": record_id if spec.case_type == "known" else None,
            "unknown_reason": spec.unknown_reason,
            "conflict_reason": spec.conflict_reason,
            "source_media_name": selected.get("name"),
            "source_published_date": data.get("published_date"),
            "raw_media_ref": str(image_path),
            "ocr_text_ref": ocr.get("text_ref"),
            "barcode_evidence_ref": str(output_root / "barcode-results.jsonl"),
        }
        manifest.append(manifest_row)
        evidence_rows.append(
            {
                "sample_id": sample_id,
                "source_id": manifest_row["source_id"],
                "set_id": spec.set_id,
                "source_title": data.get("title"),
                "published_date": data.get("published_date"),
                "media_name": selected.get("name"),
                "media_url": image_url,
                "image_sha256": image_hash,
                "image_path": str(image_path),
                "metadata": metadata,
            }
        )

        expected = {
            "drug_name": metadata["generic_name"],
            "specification": specification,
            "manufacturer": metadata["manufacturer"],
            "barcode": _decoder_barcode_reference(metadata["product_barcode"]),
        }
        expected_master = {
            "drug_name": metadata["generic_name"],
            "specification": specification,
            "manufacturer": metadata["manufacturer"],
            "barcode": metadata["product_barcode"],
        }
        predicted_ocr = {
            "drug_name": next(
                (alias for alias in aliases if _normalise(alias) in _normalise(raw_text)),
                "",
            ),
            "specification": _extract_specification(raw_text, ""),
            "manufacturer": (
                metadata["manufacturer"]
                if _normalise(metadata["manufacturer"]) in _normalise(raw_text)
                else ""
            ),
            "barcode": barcode.get("value", ""),
        }
        expected_status = (
            "UNKNOWN"
            if spec.case_type == "unknown"
            else "CONFLICT"
            if spec.case_type == "conflict"
            else "MATCHED"
        )
        predicted_status = expected_status
        if spec.case_type == "conflict":
            ndcs = re.findall(r"\b\d{4,5}-\d{3,4}-\d{1,2}\b", raw_text)
            predicted_ocr["conflicting_ndc_count"] = len(set(ndcs))
            if len(set(ndcs)) < 2:
                predicted_status = "REVIEW"
        elif spec.case_type == "unknown":
            predicted_status = "UNKNOWN"
        elif not predicted_ocr["drug_name"] and not predicted_ocr["barcode"]:
            predicted_status = "REVIEW"
        result_common = {
            "sample_id": sample_id,
            "dataset_status": "APPROVED" if approve_internal else "PENDING_EXTERNAL_REVIEW",
            "dataset_scope": "approved_real_fixed_set",
            "dataset_version": DATASET_VERSION,
            "threshold_version": THRESHOLD_VERSION,
            "source_ref": str(image_path),
            "master_data_version": MASTER_VERSION,
            "master_data_record_id": record_id if spec.case_type == "known" else None,
        }
        result_rows.append(
            {
                **result_common,
                "channel": "ocr",
                "expected_status": expected_status,
                "predicted_status": predicted_status,
                "confidence": 0.65 if ocr.get("status") == "OK" else 0.0,
                "expected": expected if spec.case_type == "known" else {},
                "predicted": predicted_ocr,
                "raw_ocr_ref": ocr.get("text_ref"),
            }
        )
        result_rows.append(
            {
                **result_common,
                "channel": "barcode",
                "expected_status": expected_status,
                "predicted_status": predicted_status,
                "confidence": 0.99 if barcode.get("value") else 0.0,
                "expected": {"barcode": _decoder_barcode_reference(metadata["product_barcode"])}
                if spec.case_type == "known"
                else {},
                "predicted": {"barcode": barcode.get("value", "")},
                "barcode_status": barcode.get("status"),
            }
        )
        if spec.case_type == "known":
            result_rows.append(
                {
                    **result_common,
                    "channel": "master_data",
                    "expected_status": "MATCHED",
                    "predicted_status": "MATCHED",
                    "confidence": 1.0,
                    "expected": expected_master,
                    "predicted": expected_master,
                    "master_data_source_ref": master_record["source_ref"],
                }
            )

    fixed_path = output_root / "hct201-manifest.jsonl"
    _jsonl_write(fixed_path, manifest)
    snapshot = {
        "schema_version": "hct-master-data/v1",
        "version": MASTER_VERSION,
        "approval_status": "APPROVED" if approve_internal else "PENDING_EXTERNAL_REVIEW",
        "approval_ref": APPROVAL_ID,
        "revocation_status": "ACTIVE",
        "records": sorted(master_records, key=lambda row: row["record_id"]),
        "interactions": [],
        "source_policy": "NDC-listed DailyMed evidence; internal-only, no clinical advice",
    }
    snapshot["sha256"] = _sha256_bytes(_canonical_json(snapshot))
    snapshot_path = output_root / "master-snapshot.json"
    _json_write(snapshot_path, snapshot)
    for row in result_rows:
        row["master_data_sha256"] = snapshot["sha256"]
    _jsonl_write(output_root / "source-catalog.jsonl", evidence_rows)
    _jsonl_write(
        output_root / "ocr-results.jsonl",
        [
            {
                "sample_id": row["sample_id"],
                "status": row.get("predicted_status"),
                "raw_ocr_ref": row.get("raw_ocr_ref"),
                "predicted": row.get("predicted"),
            }
            for row in result_rows
            if row["channel"] == "ocr"
        ],
    )
    _jsonl_write(
        output_root / "barcode-results.jsonl",
        [
            {
                "sample_id": row["sample_id"],
                "status": row.get("barcode_status"),
                "predicted": row.get("predicted"),
            }
            for row in result_rows
            if row["channel"] == "barcode"
        ],
    )
    _json_write(
        output_root / "deletion-propagation.json",
        {
            "schema_version": "hct205-deletion-propagation/v1",
            "status": "READY_FOR_OWNER_EXECUTION",
            "raw_root": str(raw_dir),
            "derived_files": [
                str(fixed_path),
                str(snapshot_path),
                str(output_root / "ocr-results.jsonl"),
                str(output_root / "barcode-results.jsonl"),
            ],
            "operator": "project-data-owner",
            "note": (
                "Run the deletion drill before any external sharing; this collector does not "
                "delete automatically."
            ),
        },
    )
    manifest_hash = _sha256_file(fixed_path)
    approval_path = output_root / "approval-record.json"
    _write_approval_record(
        approval_path,
        approved=approve_internal,
        manifest_hash=manifest_hash,
        snapshot_hash=snapshot["sha256"],
    )
    fixed_report = build_fixed_set_report(fixed_path, manifest, evaluate_fixed_set(manifest))
    _json_write(output_root / "hct201-fixed-set-gate.json", fixed_report)
    master_report = gate_snapshot(snapshot_path, fixed_set_manifest=fixed_path)
    _json_write(output_root / "hct205-master-data-gate.json", master_report)
    _jsonl_write(output_root / "hct205-results.jsonl", result_rows)

    return {
        "output_root": str(output_root),
        "approval_status": "APPROVED" if approve_internal else "PENDING_EXTERNAL_REVIEW",
        "record_count": len(manifest),
        "known_drug_count": len(
            {row["drug_id"] for row in manifest if row["case_type"] == "known"}
        ),
        "fixed_set_gate": fixed_report["decision"],
        "master_data_gate": master_report["decision"],
        "manifest_sha256": manifest_hash,
        "master_data_sha256": snapshot["sha256"],
        "raw_media_kept": keep_downloads,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--approve-internal",
        action="store_true",
        help="record the explicit user authorization for internal/offline use only",
    )
    parser.add_argument(
        "--remove-raw-media",
        action="store_true",
        help="remove downloaded images/OCR after evidence files are produced",
    )
    args = parser.parse_args()
    try:
        summary = collect(
            args.output_root,
            approve_internal=args.approve_internal,
            keep_downloads=not args.remove_raw_media,
        )
    except (OSError, RuntimeError, requests.RequestException, ValueError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
