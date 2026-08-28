"""HCT-414 / #246 剩余项第 2 条：识别链路后半段的 CPU P95 探针。

现有 ``scripts/hct414_video_perf.py`` 只测「容器解码 → 抽帧 → 近重复剔除 →
逐帧质量门控」。本探针接着往下测**真实**的：

1. 条码解码（``LocalBarcodeDecoder``，走 opencv-contrib 的 BarcodeDetector）；
2. 证据归一化与字段解析（``process_evidence``）；
3. 候选融合与主数据匹配（``fuse_evidence``）。

OCR 推理**没有测**：本机未安装 paddleocr，``LocalPaddleOCR.available`` 为假，
硬跑只会测到「空 token 的降级路径」，那不是 OCR 的真实成本。报告里以
``stages_not_measured`` 显式披露，不许静默当成已测。

夹具是按 EAN-13 模块图案直接画出来的合成条码，无药品实拍、无真实健康数据，
运行结束即删；只记录哈希、时延与硬件标识。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

REPORT_SCHEMA = "hct414-fullchain-perf-v1"
CHAIN_P95_BUDGET_MS = 2_000.0
DEFAULT_SAMPLES = 30
VALID_BARCODE = "4006381333931"
BAD_CHECKSUM_BARCODE = "4006381333932"

_L = {
    "0": "0001101", "1": "0011001", "2": "0010011", "3": "0111101", "4": "0100011",
    "5": "0110001", "6": "0101111", "7": "0111011", "8": "0110111", "9": "0001011",
}
_G = {
    "0": "0100111", "1": "0110011", "2": "0011011", "3": "0100001", "4": "0011101",
    "5": "0111001", "6": "0000101", "7": "0010001", "8": "0001001", "9": "0010111",
}
_R = {k: "".join("1" if c == "0" else "0" for c in v) for k, v in _L.items()}
_PARITY = {
    "0": "LLLLLL", "1": "LLGLGG", "2": "LLGGLG", "3": "LLGGGL", "4": "LGLLGG",
    "5": "LGGLLG", "6": "LGGGLL", "7": "LGLGLG", "8": "LGLGGL", "9": "LGGLGL",
}


def ean13_checksum(first12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def ean13_modules(code13: str) -> str:
    """EAN-13 的 95 个模块位；不校验校验位，便于生成受控拒绝样例。"""
    if len(code13) != 13 or not code13.isdigit():
        raise ValueError("EAN-13 需要 13 位数字")
    bits = ["101"]
    for digit, side in zip(code13[1:7], _PARITY[code13[0]], strict=True):
        bits.append((_L if side == "L" else _G)[digit])
    bits.append("01010")
    for digit in code13[7:]:
        bits.append(_R[digit])
    bits.append("101")
    return "".join(bits)


def render_barcode(code13: str, module_px: int, height: int, quiet: int = 12) -> Any:
    import cv2
    import numpy as np

    bits = ean13_modules(code13)
    width = (len(bits) + quiet * 2) * module_px
    img = np.full((height, width), 255, dtype=np.uint8)
    x = quiet * module_px
    for bit in bits:
        if bit == "1":
            img[:, x : x + module_px] = 0
        x += module_px
    img[:16, :] = 255
    img[-40:, :] = 255
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


@dataclass(frozen=True)
class RenderConfig:
    module_px: int
    height: int


# opencv 的 BarcodeDetector 对模块宽度/高度比例敏感，可解码窗口很窄，
# 因此在生成夹具时实测扫一遍并把命中的参数写进报告，而不是写死一个魔法值。
CANDIDATE_RENDERS = tuple(
    RenderConfig(mp, h) for mp in (2, 3, 1, 4) for h in (180, 120, 240, 360)
)


def write_fixture(directory: Path, code13: str) -> tuple[Path, RenderConfig | None, str]:
    """写出条码夹具；返回 (路径, 命中的渲染参数或 None, 解码到的内容)。"""
    import cv2
    from ai.vision.local_ocr import LocalBarcodeDecoder

    decoder = LocalBarcodeDecoder()
    path = directory / f"barcode-{code13}.png"
    for config in CANDIDATE_RENDERS:
        cv2.imwrite(str(path), render_barcode(code13, config.module_px, config.height))
        decoded = decoder.decode(path)
        if decoded and decoded[0].raw_value == code13:
            return path, config, decoded[0].raw_value
    # 一个都没命中：保留最后一次渲染，交由调用方按「未解码」处理
    return path, None, ""


def build_request(barcode_value: str, *, name: str = "Demo Medicine") -> Any:
    """合成 OCR token 与字段候选。

    OCR token 是**合成的**，不是真实 OCR 输出——本机没有 paddleocr。这样做是为了
    让归一化与融合两级跑在真实实现上；OCR 自身的成本在报告里标为未测。
    """
    from ai.vision.evidence_pipeline import (
        BarcodeCandidate,
        EvidencePipelineRequest,
        FieldProposal,
        OCRToken,
    )

    tokens = [
        ("ocr-name", name), ("ocr-spec", "10mg"), ("ocr-maker", "Demo Labs"),
        ("ocr-batch", "B123"), ("ocr-expiry", "2030-01"), ("ocr-pack", "medicine_box"),
    ]
    fields = [
        ("drug_name", name, "ocr-name"),
        ("specification", "10mg", "ocr-spec"),
        ("manufacturer", "Demo Labs", "ocr-maker"),
        ("batch_number", "B123", "ocr-batch"),
        ("expiry_date", "2030-01", "ocr-expiry"),
        ("product_barcode", barcode_value, "barcode-1"),
        ("packaging_type", "medicine_box", "ocr-pack"),
    ]
    return EvidencePipelineRequest(
        ocr_tokens=[
            OCRToken(id=tid, raw_value=val, confidence=0.95, engine_version="synthetic-ocr")
            for tid, val in tokens
        ],
        barcodes=[
            BarcodeCandidate(
                id="barcode-1", raw_value=barcode_value, format="EAN-13",
                confidence=0.98, decoder_version="measured-at-runtime",
            )
        ],
        field_proposals=[
            FieldProposal(
                field_name=fname, raw_value=val, evidence_ids=[eid],
                confidence=0.93, parser_version="parser-v1",
            )
            for fname, val, eid in fields
        ],
        vision_model_version="not-measured",
        ocr_engine_version="synthetic-ocr",
        barcode_decoder_version="measured-at-runtime",
        master_data_version="master-v1",
    )


def build_master(*, available: bool = True) -> Any:
    from ai.vision.evidence_pipeline import LocalMasterData, MasterDataRecord

    if not available:
        return LocalMasterData(version="missing", available=False, records=[])
    return LocalMasterData(
        version="master-v1",
        available=True,
        records=[
            MasterDataRecord(
                record_id="demo-1", product_barcode=VALID_BARCODE,
                name_aliases=["Demo Medicine"], specification="10mg",
                manufacturer="Demo Labs", packaging_type="medicine_box",
            ),
            MasterDataRecord(
                record_id="other-1", product_barcode=VALID_BARCODE,
                name_aliases=["Other Medicine"],
            ),
        ],
    )


def _stats(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    p95_index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return {
        "count": len(ordered),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "max_ms": round(ordered[-1], 3),
    }


def _rss_mb() -> float | None:
    """进程 RSS（MB）。与 scripts/hct414_video_perf.py 一致改用 psutil。"""
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / 1024 / 1024, 3)
    except Exception:
        return None


def ocr_availability() -> dict[str, Any]:
    """只探测可用性，不计时——不可用时计时等于测降级路径，无意义。"""
    from ai.vision.local_ocr import LocalPaddleOCR

    engine = LocalPaddleOCR()
    available = bool(engine.available)
    reason = None
    if not available:
        try:
            import paddleocr  # noqa: F401
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
    return {"available": available, "unavailable_reason": reason}


def measure(samples: int, workdir: Path) -> dict[str, Any]:
    from ai.vision.candidate_fusion import fuse_evidence
    from ai.vision.evidence_pipeline import process_evidence
    from ai.vision.local_ocr import LocalBarcodeDecoder

    decoder = LocalBarcodeDecoder()
    fixture, config, decoded_value = write_fixture(workdir, VALID_BARCODE)
    raw = fixture.read_bytes()
    fixture_info = {
        "file_name": fixture.name,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "render": {"module_px": config.module_px, "height": config.height} if config else None,
        "decoded_value": decoded_value,
        "decoder_version": decoder.decoder_version,
    }
    if config is None:
        raise SystemExit(
            "夹具在所有候选渲染参数下都无法被 opencv 解码，无法测量条码级；"
            "请检查 opencv-contrib 是否带 barcode 模块。"
        )

    master = build_master()
    stage_samples: dict[str, list[float]] = {
        "barcode_decode": [], "evidence_normalize": [], "fusion_match": []
    }
    chain_samples: list[float] = []
    last_status = None

    for _ in range(samples):
        chain_start = time.perf_counter()

        start = time.perf_counter()
        candidates = decoder.decode(fixture)
        stage_samples["barcode_decode"].append((time.perf_counter() - start) * 1000)
        if not candidates or candidates[0].raw_value != VALID_BARCODE:
            raise SystemExit("条码夹具在测量过程中解码失败，报告作废")

        request = build_request(candidates[0].raw_value)
        start = time.perf_counter()
        evidence = process_evidence(request, master_data=master)
        stage_samples["evidence_normalize"].append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        fusion = fuse_evidence(evidence, master)
        stage_samples["fusion_match"].append((time.perf_counter() - start) * 1000)

        chain_samples.append((time.perf_counter() - chain_start) * 1000)
        last_status = fusion.status.value if hasattr(fusion.status, "value") else str(fusion.status)

    return {
        "fixture": fixture_info,
        "stages": {name: _stats(values) for name, values in stage_samples.items()},
        "chain": _stats(chain_samples),
        "matched_status": last_status,
        "requires_human_confirmation": bool(fusion.requires_human_confirmation),
        "health_event_allowed": bool(fusion.health_event_allowed),
    }


def rejection_samples(workdir: Path) -> list[dict[str, Any]]:
    """受控拒绝样例：期望在写入健康事件之前被拦住。"""
    import cv2
    import numpy as np
    from ai.vision.candidate_fusion import fuse_evidence
    from ai.vision.evidence_pipeline import process_evidence
    from ai.vision.local_ocr import LocalBarcodeDecoder

    decoder = LocalBarcodeDecoder()
    out: list[dict[str, Any]] = []

    # 1) 校验位错误的条码
    request = build_request(BAD_CHECKSUM_BARCODE)
    fusion = fuse_evidence(process_evidence(request, master_data=build_master()), build_master())
    status = fusion.status.value if hasattr(fusion.status, "value") else str(fusion.status)
    out.append({
        "sample": "barcode_bad_checksum",
        "expected": "not MATCHED + BARCODE_INVALID_CHECKSUM",
        "observed_status": status,
        "observed_reasons": sorted(fusion.reasons),
        "rejected": status != "MATCHED" and "BARCODE_INVALID_CHECKSUM" in fusion.reasons,
        "health_event_allowed": bool(fusion.health_event_allowed),
    })

    # 2) 主数据不可用
    request = build_request(VALID_BARCODE)
    unavailable = build_master(available=False)
    fusion = fuse_evidence(process_evidence(request, master_data=unavailable), unavailable)
    status = fusion.status.value if hasattr(fusion.status, "value") else str(fusion.status)
    out.append({
        "sample": "master_data_unavailable",
        "expected": "not MATCHED + health_event_allowed=false",
        "observed_status": status,
        "observed_reasons": sorted(fusion.reasons),
        "rejected": status != "MATCHED" and not fusion.health_event_allowed,
        "health_event_allowed": bool(fusion.health_event_allowed),
    })

    # 3) 空白图：条码解码应返回空，而不是抛异常
    blank = workdir / "blank.png"
    cv2.imwrite(str(blank), np.full((240, 480, 3), 255, dtype=np.uint8))
    decoded = decoder.decode(blank)
    out.append({
        "sample": "blank_image_no_barcode",
        "expected": "decode returns empty list",
        "observed_candidates": len(decoded),
        "rejected": len(decoded) == 0,
        "health_event_allowed": False,
    })

    # 4) 名称与主数据冲突
    request = build_request(VALID_BARCODE, name="Totally Different Drug")
    fusion = fuse_evidence(process_evidence(request, master_data=build_master()), build_master())
    status = fusion.status.value if hasattr(fusion.status, "value") else str(fusion.status)
    out.append({
        "sample": "name_conflicts_master_data",
        "expected": "not MATCHED（进入 REVIEW/CONFLICT/UNKNOWN）",
        "observed_status": status,
        "observed_reasons": sorted(fusion.reasons),
        "rejected": status != "MATCHED",
        "health_event_allowed": bool(fusion.health_event_allowed),
    })
    return out


def build_report(samples: int, workdir: Path) -> dict[str, Any]:
    rss_before = _rss_mb()
    measured = measure(samples, workdir)
    failures = rejection_samples(workdir)
    rss_after = _rss_mb()

    chain_p95 = measured["chain"]["p95_ms"]
    accepted_by_mistake = [f["sample"] for f in failures if not f["rejected"]]
    return {
        "schema_version": REPORT_SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "issue": "#246 剩余项第 2 条（识别链路后半段 CPU P95）",
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "cpu_count": __import__("os").cpu_count(),
        },
        "memory": {
            "rss_before_mb": rss_before,
            "rss_after_mb": rss_after,
            "rss_delta_mb": (
                round(rss_after - rss_before, 3)
                if rss_before is not None and rss_after is not None
                else None
            ),
        },
        "samples": samples,
        "fixture": measured["fixture"],
        "stages_measured": measured["stages"],
        "chain": measured["chain"],
        "chain_p95_budget_ms": CHAIN_P95_BUDGET_MS,
        "within_budget": chain_p95 <= CHAIN_P95_BUDGET_MS,
        "matched_case": {
            "status": measured["matched_status"],
            "requires_human_confirmation": measured["requires_human_confirmation"],
            "health_event_allowed": measured["health_event_allowed"],
        },
        "failure_samples": failures,
        "unexpectedly_accepted": accepted_by_mistake,
        "ocr": ocr_availability(),
        "stages_not_measured": [
            "OCR 推理（paddleocr 未安装；跑它只会测到空 token 的降级路径）",
            "抽帧与逐帧质量门控（已由 scripts/hct414_video_perf.py 覆盖，不重复）",
            "人工复核交接（需要 API + 数据库，属端到端联调）",
            "并发与多主机压测（#246 剩余项第 4 条）",
        ],
        "release_status": "DEMO_ONLY",
        "release_blockers": [
            "HCT-201（#48）授权固定集未发布，无准确率结论",
            "OCR 推理成本未测",
            "人工复核交接未测",
            "并发与多主机压测未做",
        ],
        "privacy": {
            "synthetic_fixtures_only": True,
            "real_medicine_photos": False,
            "real_health_data": False,
            "fixtures_deleted_after_run": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "artifacts" / "hct414-fullchain-perf.json",
    )
    parser.add_argument(
        "--basetemp",
        type=Path,
        default=None,
        help="夹具目录；本机 %%TEMP%% 有权限限制时可指向可写目录。",
    )
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples 至少为 1")

    with tempfile.TemporaryDirectory(dir=args.basetemp) as tmp:
        report = build_report(args.samples, Path(tmp))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    chain = report["chain"]
    print(f"报告: {args.output}")
    print(f"样本数: {report['samples']}")
    for name, stats in report["stages_measured"].items():
        print(
            f"  {name:20s} p50={stats['p50_ms']:9.3f}ms "
            f"p95={stats['p95_ms']:9.3f}ms max={stats['max_ms']:9.3f}ms"
        )
    print(
        f"  {'chain(total)':20s} p50={chain['p50_ms']:9.3f}ms "
        f"p95={chain['p95_ms']:9.3f}ms max={chain['max_ms']:9.3f}ms "
        f"预算={CHAIN_P95_BUDGET_MS:.0f}ms"
    )
    print(f"融合终态: {report['matched_case']['status']}（需人工确认: "
          f"{report['matched_case']['requires_human_confirmation']}）")
    for sample in report["failure_samples"]:
        mark = "拒绝" if sample["rejected"] else "**未拒绝**"
        print(f"  受控拒绝 {sample['sample']:28s} -> {mark}")
    ocr = report["ocr"]
    print(f"OCR: available={ocr['available']} reason={ocr['unavailable_reason']}")
    print(f"release_status: {report['release_status']}")

    failed = False
    if not report["within_budget"]:
        print(
            f"阻断: 链路 P95 {chain['p95_ms']}ms 超过预算 {CHAIN_P95_BUDGET_MS}ms",
            file=sys.stderr,
        )
        failed = True
    if report["unexpectedly_accepted"]:
        print(
            "阻断: 本应拒绝却被接受的样例 -> "
            + ", ".join(report["unexpectedly_accepted"]),
            file=sys.stderr,
        )
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
