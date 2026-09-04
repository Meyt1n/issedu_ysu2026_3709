"""Local experimental model adapters: YOLO box-assist and LLM field extractor.

Both adapters run inside the family trusted domain (adapter process, not the
API). They are disabled by default and only activate when weights paths are
explicitly configured through environment variables. Weights stay outside Git.

Governance boundaries (HCT-203 / HCT-205 / AI-RAG spec):

* The YOLO model only proposes package/crop regions. It never identifies a
  medicine, never overrides OCR or barcode evidence, and its proposals cannot
  become field values on their own (the evidence pipeline rejects YOLO-only
  fields except ``packaging_type``).
* The LLM only classifies existing OCR/barcode candidates into field
  proposals. Values that do not appear verbatim in the provided evidence are
  dropped locally (anti-hallucination), and the server-side pipeline
  re-validates every proposal against evidence.
* Model versions are reported by this serving layer from artifact hashes;
  self-reported metadata from the LLM output is ignored.
* Everything stays ``EXPERIMENTAL_UNRELEASED``: results always require human
  confirmation downstream and never write health facts.

Environment variables (all optional; the bundled local model is the default):

``HCT_VISION_WEIGHTS``     override path to the YOLO ``best.pt`` (outside Git)
``HCT_VISION_DEVICE``      ``cpu`` (default) or a CUDA index such as ``0``
``HCT_VISION_CONF``        detection confidence threshold (default ``0.25``)
``HCT_LLM_BASE_MODEL``     path to the local Qwen3-4B base directory
``HCT_LLM_ADAPTER``        path to the LoRA adapter directory
``HCT_LLM_DEVICE``         ``0`` (default) CUDA index for 4-bit inference
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai.vision.evidence_pipeline import (
    BarcodeCandidate,
    EvidenceRegion,
    FieldProposal,
    OCRToken,
    PackageRegionProposal,
)

logger = logging.getLogger(__name__)

YOLO_REGISTRY_MODEL_ID = "hct-yolo11n-box-assist-experimental-v1.2-opt-a"
LLM_REGISTRY_MODEL_ID = "hct402-opt-qlora-v5"
UNAVAILABLE = "unavailable"

# Registry hash of the approved-for-experiment weights; a mismatch is recorded
# in the reported version string so an unexpected artifact is visible.
# Current registration: hct201_v1.2_opt_a_augplus_20260813/weights/best.pt
YOLO_REGISTRY_WEIGHTS_SHA256 = "b3611241787360ab517ff4169af974cd49ae46d63ccb3b3387481db1e07a8ecf"

# v4/v5 output-contract field names -> evidence-pipeline field names
FIELD_NAME_MAP = {
    "drug_name": "drug_name",
    "specification": "specification",
    "manufacturer": "manufacturer",
    "batch_number": "batch_number",
    "batch_no": "batch_number",
    "expiry_date": "expiry_date",
    "product_or_trace_code": "product_barcode",
    "product_barcode": "product_barcode",
    "barcode": "product_barcode",
    "package_type": "packaging_type",
    "packaging_type": "packaging_type",
}

LLM_SYSTEM_PROMPT = (
    "你是家庭照护证据整理器。只整理已有 OCR、条码和主数据证据，不做诊断、处方或用药判断。"
    "缺失字段不得编造，冲突必须保留；所有结果必须由用户人工确认后才能入库。"
)

DEFAULT_YOLO_WEIGHTS = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "models"
    / "vision"
    / "yolo"
    / "hct-yolo11n-box-assist-experimental-v1.2-opt-a"
    / "weights"
    / "best.pt"
)


def _default_yolo_weights() -> str | None:
    """Use the bundled demo weights when no operator override is set."""
    configured = os.environ.get("HCT_VISION_WEIGHTS")
    if configured:
        return configured
    return str(DEFAULT_YOLO_WEIGHTS) if DEFAULT_YOLO_WEIGHTS.is_file() else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse the first JSON object from generated text (code fences tolerated)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict):
        return value
    decoder = json.JSONDecoder()
    for start, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


# ── YOLO box assist ─────────────────────────────────────────────────────


@dataclass
class YoloBoxAssist:
    """Isolated-process wrapper around the experimental YOLO11n weights.

    Detection runs in the ``_yolo_worker`` subprocess: torch cannot share a
    Windows process with PaddlePaddle, and keeping the heavy runtime out of
    the adapter process means a native inference crash degrades to "no
    proposals" instead of killing the whole chain.  ``run_detect_fn`` may be
    injected for tests.
    """

    weights_path: str | None = field(
        default_factory=_default_yolo_weights
    )
    device: str = field(default_factory=lambda: os.environ.get("HCT_VISION_DEVICE", "cpu"))
    confidence: float = field(
        default_factory=lambda: float(os.environ.get("HCT_VISION_CONF", "0.25"))
    )
    timeout_seconds: int = 300
    run_detect_fn: Callable[[dict], dict] | None = None
    _version: str | None = field(default=None, repr=False)

    @property
    def available(self) -> bool:
        return bool(self.weights_path) and Path(self.weights_path).is_file()

    @property
    def model_version(self) -> str:
        if not self.available:
            return UNAVAILABLE
        if self._version is None:
            digest = _sha256_file(Path(self.weights_path))
            suffix = "" if digest == YOLO_REGISTRY_WEIGHTS_SHA256 else "-UNREGISTERED"
            self._version = f"{YOLO_REGISTRY_MODEL_ID}+{digest[:8]}{suffix}"
        return self._version

    def _detect(self, request: dict) -> dict:
        if self.run_detect_fn is not None:
            return self.run_detect_fn(request)
        from ai.vision.local_ocr import worker_python

        worker = Path(__file__).with_name("_yolo_worker.py")
        completed = subprocess.run(  # noqa: S603 (fixed worker script, no shell)
            [worker_python(), "-X", "utf8", str(worker)],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"yolo worker exited {completed.returncode}: "
                f"{(completed.stderr or '')[-500:]}"
            )
        return json.loads(completed.stdout)

    def propose_regions(self, image_path: str | Path) -> list[PackageRegionProposal]:
        """Return medicine-box crop proposals; empty when unavailable or failed."""
        if not self.available:
            logger.info("YOLO_BOX_ASSIST_UNAVAILABLE weights not configured")
            return []
        request = {
            "image_path": str(image_path),
            "weights": str(self.weights_path),
            "device": self.device,
            "conf": self.confidence,
        }
        try:
            response = self._detect(request)
        except Exception:  # inference failure must not block the OCR-first chain
            logger.exception("YOLO_BOX_ASSIST_INFERENCE_FAILED")
            return []
        proposals: list[PackageRegionProposal] = []
        for index, box in enumerate(response.get("boxes") or []):
            try:
                proposals.append(
                    PackageRegionProposal(
                        id=f"yolo-{index + 1}",
                        label="medicine_box",
                        region=EvidenceRegion(
                            x=max(float(box["x"]), 0.0),
                            y=max(float(box["y"]), 0.0),
                            width=max(float(box["width"]), 1e-3),
                            height=max(float(box["height"]), 1e-3),
                            coordinate_space="pixel",
                        ),
                        confidence=min(max(float(box["confidence"]), 0.0), 1.0),
                        model_version=self.model_version,
                    )
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("YOLO_BOX_ASSIST_BAD_BOX index=%d", index)
        return proposals


# ── LLM field extractor ─────────────────────────────────────────────────


@dataclass
class QwenLoraFieldExtractor:
    """4-bit NF4 Qwen3 + LoRA slot-filling over existing OCR/barcode evidence.

    ``generate_fn`` may be injected for tests; production lazily loads the
    quantized model on first use.
    """

    base_model_path: str | None = field(
        default_factory=lambda: os.environ.get("HCT_LLM_BASE_MODEL") or None
    )
    adapter_path: str | None = field(
        default_factory=lambda: os.environ.get("HCT_LLM_ADAPTER") or None
    )
    device: str = field(default_factory=lambda: os.environ.get("HCT_LLM_DEVICE", "0"))
    max_new_tokens: int = 512
    generate_fn: Callable[[str, str], str] | None = None
    _bundle: Any = field(default=None, repr=False)
    _version: str | None = field(default=None, repr=False)

    @property
    def available(self) -> bool:
        if self.generate_fn is not None:
            return True
        return (
            bool(self.base_model_path)
            and bool(self.adapter_path)
            and Path(self.base_model_path).is_dir()
            and Path(self.adapter_path).is_dir()
        )

    @property
    def extractor_version(self) -> str:
        if not self.available:
            return UNAVAILABLE
        if self.generate_fn is not None and not self.adapter_path:
            return f"{LLM_REGISTRY_MODEL_ID}+injected-test"
        if self._version is None:
            weights = Path(self.adapter_path) / "adapter_model.safetensors"
            digest = _sha256_file(weights)[:8] if weights.is_file() else "nohash"
            self._version = f"{LLM_REGISTRY_MODEL_ID}+{digest}-nf4"
        return self._version

    def _generate(self, system: str, user: str) -> str:
        if self.generate_fn is not None:
            return self.generate_fn(system, user)
        if self._bundle is None:
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

            tokenizer = AutoTokenizer.from_pretrained(
                self.base_model_path, local_files_only=True, use_fast=True
            )
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token
            quantization = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            )
            model = AutoModelForCausalLM.from_pretrained(
                self.base_model_path,
                local_files_only=True,
                quantization_config=quantization,
                dtype=torch.bfloat16,
                device_map={"": int(self.device) if self.device.isdigit() else self.device},
                low_cpu_mem_usage=True,
            )
            model = PeftModel.from_pretrained(
                model, self.adapter_path, local_files_only=True, is_trainable=False
            )
            model.eval()
            self._bundle = (tokenizer, model, torch)
        tokenizer, model, torch = self._bundle
        prompt = tokenizer.apply_chat_template(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024).to(
            model.device
        )
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        return tokenizer.decode(
            output[0, inputs["input_ids"].shape[-1] :], skip_special_tokens=True
        ).strip()

    @staticmethod
    def build_user_message(
        ocr_tokens: list[OCRToken],
        barcodes: list[BarcodeCandidate],
        package_labels: list[str],
    ) -> str:
        parts: list[str] = []
        for token in ocr_tokens:
            parts.append(
                f"OCR token {token.id}={token.raw_value}（置信度{token.confidence:.2f}）"
            )
        for barcode in barcodes:
            state = "解码成功" if barcode.decode_valid else "解码待验证"
            parts.append(
                f"条码解码 {barcode.id}={barcode.raw_value}"
                f"（置信度{barcode.confidence:.2f}，{state}）"
            )
        for index, label in enumerate(package_labels, 1):
            parts.append(f"包装候选 package-{index}={label}")
        return "；".join(parts) + "。请把以上候选整理为结构化字段，标注来源和状态。"

    def extract_fields(
        self,
        ocr_tokens: list[OCRToken],
        barcodes: list[BarcodeCandidate],
        package_labels: list[str] | None = None,
    ) -> list[FieldProposal]:
        """Classify existing candidates into field proposals.

        Anything the model invents (value not present verbatim in the supplied
        evidence, or unknown evidence id) is dropped and logged.
        """
        if not self.available:
            logger.info("LLM_FIELD_EXTRACTOR_UNAVAILABLE model paths not configured")
            return []
        if not ocr_tokens and not barcodes:
            return []
        user = self.build_user_message(ocr_tokens, barcodes, package_labels or [])
        try:
            raw = self._generate(LLM_SYSTEM_PROMPT, user)
        except Exception:
            logger.exception("LLM_FIELD_EXTRACTOR_INFERENCE_FAILED")
            return []
        parsed = extract_json_object(raw)
        if parsed is None or not isinstance(parsed.get("fields"), dict):
            logger.warning("LLM_FIELD_EXTRACTOR_BAD_OUTPUT no parseable fields object")
            return []

        known_values = {token.id: token.raw_value for token in ocr_tokens}
        known_values.update({barcode.id: barcode.raw_value for barcode in barcodes})

        proposals: list[FieldProposal] = []
        for raw_name, item in parsed["fields"].items():
            field_name = FIELD_NAME_MAP.get(str(raw_name))
            if field_name is None or not isinstance(item, dict):
                continue
            value = item.get("raw_value")
            if not isinstance(value, str) or not value.strip():
                continue  # null/absent means missing evidence; never invent
            evidence_ids = [
                evidence_id
                for evidence_id in item.get("source_region_ids", [])
                if isinstance(evidence_id, str) and evidence_id in known_values
            ]
            if not evidence_ids:
                logger.warning(
                    "LLM_PROPOSAL_DROPPED field=%s reason=no-known-evidence-id", field_name
                )
                continue
            # Verbatim rule: the value must be a literal substring of one of
            # the evidence items it cites.  Checking a space-joined haystack
            # of *all* evidence would let a value spliced across two tokens
            # pass the local guard (the server-side pipeline would still
            # reject it, but the documented local guarantee must hold here).
            if not any(value in known_values[evidence_id] for evidence_id in evidence_ids):
                logger.warning(
                    "LLM_PROPOSAL_DROPPED field=%s reason=value-not-in-evidence", field_name
                )
                continue
            try:
                confidence = min(max(float(item.get("confidence", 0.0)), 0.0), 1.0)
            except (TypeError, ValueError):
                confidence = 0.0
            proposals.append(
                FieldProposal(
                    field_name=field_name,  # type: ignore[arg-type]
                    raw_value=value,
                    evidence_ids=evidence_ids,
                    confidence=confidence,
                    parser_version=self.extractor_version,
                    source="llm",
                )
            )
        return proposals
