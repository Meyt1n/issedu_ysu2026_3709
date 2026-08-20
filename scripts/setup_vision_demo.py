"""Generate the local master-data snapshot used by the vision closed-loop demo.

Writes ``data/master-data/demo-cn-en-v1.json`` (runtime directory, not
committed) in the checked ``hct-master-data/v1`` format with a canonical
SHA-256, so ``load_master_data_snapshot`` accepts it once the version is
approved via ``MASTER_DATA_APPROVED_VERSIONS=demo-cn-en-v1``.

The records are synthetic teaching data (no real product master data).

Usage:
    uv run python scripts/setup_vision_demo.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = REPO_ROOT / "data" / "master-data"
VERSION = "demo-cn-en-v1"

RECORDS = [
    {
        "record_id": "rec-amoxicillin-cn",
        "product_barcode": "6901234567892",
        "name_aliases": [
            "阿莫西林胶囊",
            "阿莫西林",
            "Amoxicillin Capsules",
            "AMOXICILLIN CAPSULES",
        ],
        "specification": "0.25g×24粒",
        "manufacturer": "家健示例制药有限公司",
        "packaging_type": "box",
        "active_ingredients": ["阿莫西林"],
        "indications": ["用于演示的细菌感染相关用药信息核对"],
        "cautions": ["使用前核对说明书、过敏史和当前医嘱"],
        "contraindications": ["对青霉素类或本品成分过敏者需先人工核对"],
    },
    {
        "record_id": "rec-ibuprofen-en",
        "product_barcode": "5012345678900",
        "name_aliases": [
            "Ibuprofen Tablets",
            "IBUPROFEN TABLETS",
            # 常见 OCR 变体：中文模型识别拉丁文会丢失空格
            "IbuprofenTablets",
            "Ibuprofen",
            "IBUPROFEN",
            "布洛芬片",
        ],
        "specification": "200mgx20",
        "manufacturer": "HomeCare Demo Pharma",
        "packaging_type": "box",
        "active_ingredients": ["布洛芬"],
        "indications": ["用于演示的疼痛或发热信息核对"],
        "cautions": ["使用前核对说明书、胃肠道风险和当前医嘱"],
        "contraindications": ["对本品或相关解热镇痛药过敏者需先人工核对"],
    },
]


def canonical(payload: dict) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def main() -> None:
    snapshot = {
        "schema_version": "hct-master-data/v1",
        "version": VERSION,
        "approval_status": "APPROVED",
        "approval_ref": "docs/demo/受控演示知识说明（教学合成数据）",
        "revocation_status": "ACTIVE",
        "records": RECORDS,
        "interactions": [
            {
                "record_ids": ["rec-amoxicillin-cn", "rec-ibuprofen-en"],
                "level": "INFO",
                "message": (
                    "本地演示主数据要求核对这两种药品的当前医嘱和说明书；"
                    "系统不判断是否可以同用。"
                ),
            }
        ],
    }
    snapshot["sha256"] = hashlib.sha256(canonical(snapshot)).hexdigest()

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    target = SNAPSHOT_DIR / f"{VERSION}.json"
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"master-data snapshot written: {target}")
    print(f"records: {len(RECORDS)} · sha256: {snapshot['sha256'][:16]}…")
    print()
    print("启动后端时需要批准该版本（示例）：")
    print('  $env:MASTER_DATA_APPROVED_VERSIONS = "demo-cn-en-v1"')


if __name__ == "__main__":
    main()
