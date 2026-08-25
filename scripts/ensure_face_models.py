#!/usr/bin/env python3
"""Ensure local YuNet + SFace ONNX weights exist under models/face/.

Weights are intentionally not committed.  Run once on a machine that can reach
OpenCV Zoo, or copy the two ONNX files into FACE_MODEL_DIR manually.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "api"))

from app.face_credentials import ensure_face_models  # noqa: E402


def main() -> int:
    yunet, sface = ensure_face_models()
    print(f"yunet={yunet}")
    print(f"sface={sface}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
