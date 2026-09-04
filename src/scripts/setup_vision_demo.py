"""Generate the local master-data snapshot used by the vision closed-loop demo.

Writes ``src/runtime/data/master-data/demo-cn-en-v1.json`` (runtime directory, not
committed) in the checked ``hct-master-data/v1`` format with a canonical
SHA-256, so ``load_master_data_snapshot`` accepts it once the version is
approved via ``MASTER_DATA_APPROVED_VERSIONS=demo-cn-en-v1``.

The records are synthetic teaching data (no real product master data).  The
snapshot carries machine-readable INTERNAL_TEACHING_DEMO scope markers from
``docs/data/HCT-201-教学演示批准范围-V1.md``: it may power local teaching
demos, but it is not — and must never be registered as — the formal HCT-201
released drug set, which stays UNRELEASED until the fixed-set gate passes.

Usage:
    uv run python scripts/setup_vision_demo.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = REPO_ROOT / "src" / "runtime" / "data" / "master-data"
VERSION = "demo-cn-en-v1"
APPROVAL_REF = "doc/ 中的 HCT-201 教学演示批准范围说明"

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


def build_snapshot() -> dict:
    """Build the teaching-demo snapshot with its canonical SHA-256.

    The extra ``approval_scope`` / ``*_eligible`` keys are honest scope
    markers (they participate in the hash): this snapshot is approved for
    INTERNAL_TEACHING_DEMO only and can never satisfy the formal HCT-201
    fixed-set gate.
    """
    snapshot = {
        "schema_version": "hct-master-data/v1",
        "version": VERSION,
        "approval_status": "APPROVED",
        "approval_scope": "INTERNAL_TEACHING_DEMO",
        "formal_release_eligible": False,
        "production_eligible": False,
        "approval_ref": APPROVAL_REF,
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
    return snapshot


def write_snapshot(target_dir: Path) -> Path:
    snapshot = build_snapshot()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{VERSION}.json"
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def main() -> None:
    target = write_snapshot(SNAPSHOT_DIR)
    snapshot = json.loads(target.read_text(encoding="utf-8"))
    print(f"master-data snapshot written: {target}")
    print(f"records: {len(RECORDS)} · sha256: {snapshot['sha256'][:16]}…")
    print()
    print("该快照仅限教学演示（INTERNAL_TEACHING_DEMO），不是 HCT-201 正式药品集。")
    print("启动后端时需要批准该版本（示例）：")
    print('  $env:MASTER_DATA_APPROVED_VERSIONS = "demo-cn-en-v1"')


if __name__ == "__main__":
    main()
