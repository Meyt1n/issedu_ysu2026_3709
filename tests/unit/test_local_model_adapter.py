"""Unit tests for the local experimental model adapters.

No real model weights are loaded: YOLO tests cover the unavailable/degraded
paths, and the LLM extractor uses an injected generate function. The heavy
dependencies (ultralytics/transformers) are never imported here.
"""

from __future__ import annotations

import json

from ai.vision.evidence_pipeline import (
    BarcodeCandidate,
    EvidencePipelineRequest,
    OCRToken,
    process_evidence,
)
from ai.vision.local_models import (
    QwenLoraFieldExtractor,
    YoloBoxAssist,
    extract_json_object,
)


def _tokens() -> list[OCRToken]:
    return [
        OCRToken(id="ocr-1-name", raw_value="演示药甲片", confidence=0.97, engine_version="ocr-v1"),
        OCRToken(id="ocr-1-spec", raw_value="0.25g×24片", confidence=0.9, engine_version="ocr-v1"),
        OCRToken(id="ocr-1-expiry", raw_value="2027-05", confidence=0.91, engine_version="ocr-v1"),
    ]


def _barcodes() -> list[BarcodeCandidate]:
    return [
        BarcodeCandidate(
            id="code-1",
            raw_value="4006381333931",
            confidence=0.99,
            format="EAN-13",
            decoder_version="decoder-v1",
            decode_valid=True,
        )
    ]


def _llm_output(fields: dict) -> str:
    return json.dumps(
        {
            "schema_version": "hct-llm-output/v1",
            "route": "EVIDENCE_REQUIRED",
            "status": "REVIEW",
            "fields": fields,
            "evidence": [],
            "needs_human_confirmation": True,
            "response": "已整理，仍需人工确认。",
        },
        ensure_ascii=False,
    )


def test_yolo_unavailable_without_weights(monkeypatch) -> None:
    monkeypatch.delenv("HCT_VISION_WEIGHTS", raising=False)
    yolo = YoloBoxAssist()
    assert yolo.available is False
    assert yolo.model_version == "unavailable"
    assert yolo.propose_regions("missing.jpg") == []


def test_yolo_missing_weights_path_is_unavailable(tmp_path) -> None:
    yolo = YoloBoxAssist(weights_path=str(tmp_path / "no-such-best.pt"))
    assert yolo.available is False
    assert yolo.propose_regions(tmp_path / "img.jpg") == []


def test_yolo_worker_boxes_become_proposals(tmp_path) -> None:
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"fake-weights")
    yolo = YoloBoxAssist(
        weights_path=str(weights),
        run_detect_fn=lambda request: {
            "boxes": [
                {"x": 12.0, "y": 8.0, "width": 300.0, "height": 200.0, "confidence": 0.91},
                {"x": "broken"},  # malformed entries are skipped, not fatal
            ]
        },
    )
    proposals = yolo.propose_regions(tmp_path / "img.jpg")
    assert len(proposals) == 1
    assert proposals[0].id == "yolo-1"
    assert proposals[0].label == "medicine_box"
    assert proposals[0].region.width == 300.0
    assert proposals[0].model_version.endswith("-UNREGISTERED")


def test_yolo_worker_crash_degrades_to_empty(tmp_path) -> None:
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"fake-weights")

    def boom(request: dict) -> dict:
        raise RuntimeError("yolo worker exited 3221225477")

    yolo = YoloBoxAssist(weights_path=str(weights), run_detect_fn=boom)
    assert yolo.propose_regions(tmp_path / "img.jpg") == []


def test_llm_unavailable_without_paths(monkeypatch) -> None:
    for name in ("HCT_LLM_BASE_MODEL", "HCT_LLM_ADAPTER"):
        monkeypatch.delenv(name, raising=False)
    extractor = QwenLoraFieldExtractor()
    assert extractor.available is False
    assert extractor.extractor_version == "unavailable"
    assert extractor.extract_fields(_tokens(), _barcodes()) == []


def test_llm_extracts_and_maps_contract_field_names() -> None:
    fields = {
        "drug_name": {
            "raw_value": "演示药甲片",
            "source_region_ids": ["ocr-1-name"],
            "confidence": 0.97,
        },
        "product_or_trace_code": {
            "raw_value": "4006381333931",
            "source_region_ids": ["code-1"],
            "confidence": 0.99,
        },
    }
    extractor = QwenLoraFieldExtractor(generate_fn=lambda system, user: _llm_output(fields))
    proposals = extractor.extract_fields(_tokens(), _barcodes())
    by_name = {proposal.field_name: proposal for proposal in proposals}
    assert set(by_name) == {"drug_name", "product_barcode"}
    assert by_name["drug_name"].raw_value == "演示药甲片"
    assert by_name["drug_name"].evidence_ids == ["ocr-1-name"]
    assert by_name["drug_name"].source == "llm"
    assert by_name["product_barcode"].evidence_ids == ["code-1"]


def test_llm_drops_hallucinated_values_and_unknown_ids() -> None:
    fields = {
        "drug_name": {
            # value not present in any provided evidence
            "raw_value": "编造药名片",
            "source_region_ids": ["ocr-1-name"],
            "confidence": 0.99,
        },
        "specification": {
            # unknown evidence id
            "raw_value": "0.25g×24片",
            "source_region_ids": ["ocr-999"],
            "confidence": 0.9,
        },
        "expiry_date": {
            # missing evidence must stay missing
            "raw_value": None,
            "source_region_ids": [],
            "confidence": 0.0,
        },
    }
    extractor = QwenLoraFieldExtractor(generate_fn=lambda system, user: _llm_output(fields))
    assert extractor.extract_fields(_tokens(), _barcodes()) == []


def test_llm_drops_value_spliced_across_evidence_items() -> None:
    """The verbatim rule is per evidence item, not a joined haystack.

    "演示药甲片 0.25g×24片" only exists when two separate OCR tokens are
    concatenated with a space; no single cited evidence contains it, so the
    local anti-hallucination guard must drop the proposal.
    """
    fields = {
        "drug_name": {
            "raw_value": "演示药甲片 0.25g×24片",
            "source_region_ids": ["ocr-1-name", "ocr-1-spec"],
            "confidence": 0.95,
        },
    }
    extractor = QwenLoraFieldExtractor(generate_fn=lambda system, user: _llm_output(fields))
    assert extractor.extract_fields(_tokens(), _barcodes()) == []


def test_llm_bad_output_returns_empty() -> None:
    extractor = QwenLoraFieldExtractor(generate_fn=lambda system, user: "抱歉，我不能这样做。")
    assert extractor.extract_fields(_tokens(), _barcodes()) == []


def test_llm_inference_failure_returns_empty() -> None:
    def boom(system: str, user: str) -> str:
        raise RuntimeError("cuda out of memory")

    extractor = QwenLoraFieldExtractor(generate_fn=boom)
    assert extractor.extract_fields(_tokens(), _barcodes()) == []


def test_llm_proposals_survive_evidence_pipeline() -> None:
    fields = {
        "drug_name": {
            "raw_value": "演示药甲片",
            "source_region_ids": ["ocr-1-name"],
            "confidence": 0.97,
        }
    }
    extractor = QwenLoraFieldExtractor(generate_fn=lambda system, user: _llm_output(fields))
    proposals = extractor.extract_fields(_tokens(), _barcodes())
    request = EvidencePipelineRequest(
        ocr_tokens=_tokens(),
        barcodes=_barcodes(),
        field_proposals=proposals,
        vision_model_version="hct-yolo11n-box-assist-experimental-v1.2+test",
        ocr_engine_version="ocr-v1",
    )
    result = process_evidence(request)
    assert result.requires_human_confirmation is True
    stored = {item.field_name: item for item in result.fields}
    assert "drug_name" in stored
    assert stored["drug_name"].source == "llm"
    assert stored["drug_name"].confirmation_status == "UNCONFIRMED"
    assert result.versions["vision_model_version"].startswith(
        "hct-yolo11n-box-assist-experimental-v1.2"
    )


def test_extract_json_object_variants() -> None:
    assert extract_json_object('{"a": 1}') == {"a": 1}
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('前置说明 {"a": {"b": 2}} 后置') == {"a": {"b": 2}}
    assert extract_json_object("no json here") is None
