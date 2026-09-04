"""Run the local experimental vision+LLM adapter against the HomeCare Twin API.

This adapter executes inside the family trusted domain. It performs the
quality gate, uploads the image, creates a vision task, runs the local
engines (PaddleOCR full-image OCR as the primary text channel, YOLO
box-assist for crop hints, OpenCV barcode/QR decoding, and the LLM field
extractor over the collected candidates), and submits signed OCR-first
evidence. It never confirms a medicine identity; fusion and human
confirmation stay on the server.

OCR-first order: the full image is always OCRed first; YOLO proposals only
trigger an additional OCR pass on crops whose non-duplicate tokens are added
as extra evidence. External engines can override the built-in ones via
``--ocr-json`` / ``--barcode-json`` (lists of objects with ``id``,
``raw_value``, ``confidence`` …). When no OCR source is available the adapter
still submits YOLO region proposals as a documented degraded mode.

Requirements: run inside an environment that has ``paddleocr`` (OCR,
optional), ``ultralytics`` (YOLO, optional), ``opencv-contrib`` (barcode,
optional), ``transformers``/``peft``/``bitsandbytes`` (LLM, optional) and
``requests``. Model weights stay outside Git and are configured through
environment variables (see ``src/ai/vision/local_models.py``).

Example (dry run, no API calls):
    python scripts/run_local_adapter.py --image path\\to\\box.jpg --dry-run

Example (full submission):
    python scripts/run_local_adapter.py --image path\\to\\box.jpg \
        --api http://127.0.0.1:8000/api/v1 --actor demo-user --fuse
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from ai.vision.evidence_pipeline import (  # noqa: E402
    BarcodeCandidate,
    EvidencePipelineRequest,
    OCRToken,
    issue_adapter_receipt,
)
from ai.vision.local_models import (  # noqa: E402
    QwenLoraFieldExtractor,
    YoloBoxAssist,
)
from ai.vision.local_ocr import (  # noqa: E402
    LocalBarcodeDecoder,
    LocalPaddleOCR,
)
from ai.vision.rule_fields import propose_fields  # noqa: E402

ADAPTER_ID = "homecare-local-vision"
ADAPTER_VERSION = "local-adapter-v1"


def load_json_list(path: Path | None) -> list[dict]:
    if path is None:
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise SystemExit(f"{path}: expected a JSON list")
    return value


def build_request(
    *,
    yolo: YoloBoxAssist,
    extractor: QwenLoraFieldExtractor,
    image: Path,
    ocr_rows: list[dict],
    barcode_rows: list[dict],
    run_id: str,
    local_ocr: LocalPaddleOCR | None = None,
    local_barcode: LocalBarcodeDecoder | None = None,
) -> EvidencePipelineRequest:
    # YOLO first so its crops can assist (never replace) the full-image OCR.
    package_regions = yolo.propose_regions(image)

    if ocr_rows:  # explicit external engine wins
        ocr_tokens = [
            OCRToken(
                id=row.get("id") or f"ocr-{index + 1}",
                raw_value=row["raw_value"],
                confidence=float(row.get("confidence", 0.5)),
                engine_version=row.get("engine_version", "external-ocr"),
            )
            for index, row in enumerate(ocr_rows)
        ]
    elif local_ocr is not None and local_ocr.available:
        ocr_tokens = local_ocr.recognize(image, package_regions)
    else:
        ocr_tokens = []

    if barcode_rows:
        barcodes = [
            BarcodeCandidate(
                id=row.get("id") or f"code-{index + 1}",
                raw_value=row["raw_value"],
                confidence=float(row.get("confidence", 0.9)),
                format=row.get("format", "UNKNOWN"),
                decoder_version=row.get("decoder_version", "external-decoder"),
                decode_valid=bool(row.get("decode_valid", False)),
                checksum_valid=row.get("checksum_valid"),
            )
            for index, row in enumerate(barcode_rows)
        ]
    elif local_barcode is not None and local_barcode.available:
        barcodes = local_barcode.decode(image)
    else:
        barcodes = []

    # contract order: deterministic rules/dictionary produce candidates first
    # (with verbatim sub-tokens); the LLM then only classifies existing ones
    rule_subtokens, rule_proposals = propose_fields(
        ocr_tokens, barcodes, package_regions
    )
    if rule_subtokens:
        ocr_tokens = (ocr_tokens + rule_subtokens)[:512]

    llm_proposals = extractor.extract_fields(
        ocr_tokens,
        barcodes,
        [proposal.label for proposal in package_regions],
    )
    proposals = (rule_proposals + llm_proposals)[:64]

    return EvidencePipelineRequest(
        ocr_tokens=ocr_tokens,
        barcodes=barcodes,
        package_regions=package_regions,
        field_proposals=proposals,
        vision_model_version=yolo.model_version,
        ocr_engine_version=(
            ocr_tokens[0].engine_version if ocr_tokens else "unavailable"
        ),
        barcode_decoder_version=(
            barcodes[0].decoder_version if barcodes else "unavailable"
        ),
        master_data_version=os.environ.get("HCT_MASTER_DATA_VERSION", "unavailable"),
        code_version="hct-local-adapter-v1",
        adapter_id=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        adapter_run_id=run_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--api", default=os.environ.get("HCT_API_BASE", "http://127.0.0.1:8000/api/v1"))
    parser.add_argument("--actor", default=os.environ.get("HCT_ACTOR_ID", "local-adapter-demo"))
    parser.add_argument("--ocr-json", type=Path, help="external OCR tokens (JSON list)")
    parser.add_argument("--barcode-json", type=Path, help="external barcode decodes (JSON list)")
    parser.add_argument(
        "--no-local-ocr",
        action="store_true",
        help="disable the built-in PaddleOCR engine (degraded mode without --ocr-json)",
    )
    parser.add_argument(
        "--no-local-barcode",
        action="store_true",
        help="disable the built-in OpenCV barcode/QR decoder",
    )
    parser.add_argument("--member-id", default=None)
    parser.add_argument("--fuse", action="store_true", help="run candidate fusion after evidence")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run local inference only and print the unsigned payload",
    )
    args = parser.parse_args()

    if not args.image.is_file():
        raise SystemExit(f"image not found: {args.image}")

    yolo = YoloBoxAssist()
    extractor = QwenLoraFieldExtractor()
    local_ocr = None if args.no_local_ocr else LocalPaddleOCR()
    local_barcode = None if args.no_local_barcode else LocalBarcodeDecoder()
    print(
        json.dumps(
            {
                "adapter": ADAPTER_ID,
                "yolo_available": yolo.available,
                "yolo_version": yolo.model_version,
                "ocr_available": bool(local_ocr and local_ocr.available),
                "ocr_version": (
                    local_ocr.engine_version
                    if local_ocr and local_ocr.available
                    else "unavailable"
                ),
                "barcode_available": bool(local_barcode and local_barcode.available),
                "llm_available": extractor.available,
                "llm_version": extractor.extractor_version,
                "note": "EXPERIMENTAL_UNRELEASED; results always require human confirmation",
            },
            ensure_ascii=False,
        )
    )

    run_id = f"local-{os.getpid()}"
    request = build_request(
        yolo=yolo,
        extractor=extractor,
        image=args.image,
        ocr_rows=load_json_list(args.ocr_json),
        barcode_rows=load_json_list(args.barcode_json),
        run_id=run_id,
        local_ocr=local_ocr,
        local_barcode=local_barcode,
    )

    if args.dry_run:
        print(request.model_dump_json(indent=2, exclude={"adapter_receipt"}))
        return 0

    import requests

    headers = {"X-Actor-ID": args.actor}
    content = args.image.read_bytes()
    mime = mimetypes.guess_type(args.image.name)[0] or "application/octet-stream"

    quality = requests.post(
        f"{args.api}/vision-quality/check",
        files={"file": (args.image.name, content, mime)},
        data={"media_type": "image"},
        headers=headers,
        timeout=120,
    )
    quality.raise_for_status()
    quality_body = quality.json()
    print(
        json.dumps(
            {
                "quality_decision": quality_body["decision"],
                "reasons": quality_body.get("reasons", []),
            },
            ensure_ascii=False,
        )
    )
    if quality_body["decision"] != "PASS" or not quality_body.get("quality_receipt"):
        print(
            json.dumps(
                {
                    "stopped": "QUALITY_GATE_RETAKE",
                    "retake_prompts": quality_body.get("retake_prompts", []),
                },
                ensure_ascii=False,
            )
        )
        return 2

    upload = requests.post(
        f"{args.api}/files/upload",
        files={"file": (args.image.name, content, mime)},
        headers=headers,
        timeout=120,
    )
    upload.raise_for_status()
    storage_key = upload.json()["storage_key"]

    task_response = requests.post(
        f"{args.api}/vision-tasks",
        json={
            "file_id": storage_key,
            "member_id": args.member_id,
            "quality_receipt": quality_body["quality_receipt"],
        },
        headers=headers,
        timeout=60,
    )
    task_response.raise_for_status()
    task = task_response.json()
    print(
        json.dumps(
            {"vision_task": task["id"], "input_digest": task["input_digest"]},
            ensure_ascii=False,
        )
    )

    signing_key = os.environ.get("HCT_ADAPTER_SIGNING_KEY", "dev-only-change-me")
    receipt = issue_adapter_receipt(task["id"], task["input_digest"] or "", request, signing_key)
    payload = json.loads(request.model_dump_json())
    payload["adapter_receipt"] = receipt

    evidence = requests.post(
        f"{args.api}/vision-tasks/{task['id']}/evidence",
        json=payload,
        headers=headers,
        timeout=300,
    )
    evidence.raise_for_status()
    result = evidence.json()
    print(
        json.dumps(
            {
                "fusion_readiness": result["fusion_readiness"],
                "fields": [
                    {
                        "field": item["field_name"],
                        "value": item["normalized_value"],
                        "source": item["source"],
                        "confirmation_status": item["confirmation_status"],
                    }
                    for item in result["fields"]
                ],
                "findings": [item["code"] for item in result["findings"]],
                "versions": result["versions"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if args.fuse:
        fusion = requests.post(
            f"{args.api}/vision-tasks/{task['id']}/fusion",
            json={},
            headers=headers,
            timeout=60,
        )
        fusion.raise_for_status()
        print(json.dumps({"fusion": fusion.json()}, ensure_ascii=False, indent=2))

    print("提示：以上结果均为实验模型输出，必须经人工确认后才能写入健康档案。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
