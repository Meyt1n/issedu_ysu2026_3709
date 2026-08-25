#!/usr/bin/env python3
"""Calibrate local SFace match threshold / family margin from a sample tree.

Directory layout (images only; nothing is uploaded or stored by this script)::

    samples/
      person_a/
        enroll/  *.jpg
        probe/   *.jpg
      person_b/
        enroll/
        probe/

Outputs JSON with recommended FACE_MATCH_THRESHOLD_SFACE and
FACE_MATCH_MARGIN_SFACE.  Never prints embeddings or raw scores per image path
beyond aggregate statistics.

This must be run on a maintainer machine with real household camera samples.
Cloud agents / CI cannot capture real faces for you; see
``docs/本地部署与Demo操作指南.md`` §1.3.

Usage::

    uv run python scripts/calibrate_face_thresholds.py ./samples
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "api"))

from app.face_credentials import (  # noqa: E402
    FACE_ALGORITHM_VERSION,
    extract_face_template,
    face_template_similarity,
    match_threshold_for,
)


def _load_embeddings(folder: Path) -> list[bytes]:
    embeddings: list[bytes] = []
    for path in sorted(folder.glob("*")):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        try:
            template, meta = extract_face_template(path.read_bytes(), enforce_geometry=False)
        except (ValueError, RuntimeError):
            continue
        if meta.get("algorithm_version") != FACE_ALGORITHM_VERSION:
            continue
        embeddings.append(template)
    return embeddings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples_root", type=Path)
    parser.add_argument("--false-accept-target", type=float, default=0.0)
    args = parser.parse_args()
    root: Path = args.samples_root
    if not root.is_dir():
        print(json.dumps({"error": "SAMPLES_ROOT_MISSING"}))
        return 2

    genuine: list[float] = []
    impostor: list[float] = []
    people = sorted(path for path in root.iterdir() if path.is_dir())
    galleries: dict[str, list[bytes]] = {}
    probes: dict[str, list[bytes]] = {}
    for person in people:
        galleries[person.name] = _load_embeddings(person / "enroll")
        probes[person.name] = _load_embeddings(person / "probe")

    for name, probe_list in probes.items():
        gallery = galleries.get(name) or []
        for probe in probe_list:
            for item in gallery:
                genuine.append(face_template_similarity(probe, item))
        for other_name, other_gallery in galleries.items():
            if other_name == name:
                continue
            for probe in probe_list:
                for item in other_gallery:
                    impostor.append(face_template_similarity(probe, item))

    if not genuine or not impostor:
        print(
            json.dumps(
                {
                    "error": "INSUFFICIENT_PAIRS",
                    "genuine_pairs": len(genuine),
                    "impostor_pairs": len(impostor),
                    "hint": "Need >=1 enroll+probe pair for 2+ people",
                },
                ensure_ascii=False,
            )
        )
        return 1

    genuine_sorted = sorted(genuine)
    impostor_sorted = sorted(impostor, reverse=True)
    # Choose the lowest threshold that keeps all observed impostors below it,
    # then add a small safety margin.  Operators may loosen after camera trials.
    max_impostor = impostor_sorted[0]
    min_genuine = genuine_sorted[0]
    recommended = round(max(max_impostor + 0.05, min(0.55, (max_impostor + min_genuine) / 2)), 3)
    recommended = float(min(0.85, max(0.25, recommended)))
    margin = round(max(0.03, min(0.12, (min_genuine - recommended) / 2 or 0.05)), 3)
    payload = {
        "algorithm_version": FACE_ALGORITHM_VERSION,
        "current_threshold": match_threshold_for(FACE_ALGORITHM_VERSION),
        "genuine_pairs": len(genuine),
        "impostor_pairs": len(impostor),
        "genuine_min": round(min_genuine, 4),
        "genuine_p10": round(genuine_sorted[max(0, len(genuine_sorted) // 10)], 4),
        "impostor_max": round(max_impostor, 4),
        "recommended_FACE_MATCH_THRESHOLD_SFACE": recommended,
        "recommended_FACE_MATCH_MARGIN_SFACE": margin,
        "notes": [
            "Write values into .env and restart the API.",
            "Re-run after collecting real household camera frames.",
            "Teaching demo only; not a production biometric certification.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
