"""Isolated PaddleOCR worker process.

PaddlePaddle and PyTorch cannot share one Windows process (their native
DLLs conflict in either import order), so the adapter never imports paddle:
it spawns this worker, which never imports torch.

Protocol: a JSON request on stdin ->

    {"image_path": "...", "lang": "ch",
     "crops": [{"x": 0, "y": 0, "width": 100, "height": 80}, ...]}

and a JSON response on stdout ->

    {"full": [<paddle line>, ...], "crops": [[<paddle line>, ...], ...]}

where each paddle line is ``[quad, [text, confidence]]``. Crop entries keep
the request order; a failed crop yields an empty list. All logs go to
stderr; stdout carries exactly one JSON document.
"""

from __future__ import annotations

import json
import os
import sys


def clamp_rect(
    rect: dict, width: int, height: int, minimum: int = 8
) -> tuple[int, int, int, int] | None:
    """Clamp a pixel rect to image bounds; None when degenerate."""
    x1 = int(max(float(rect.get("x", 0)), 0))
    y1 = int(max(float(rect.get("y", 0)), 0))
    x2 = int(min(float(rect.get("x", 0)) + float(rect.get("width", 0)), width))
    y2 = int(min(float(rect.get("y", 0)) + float(rect.get("height", 0)), height))
    if x2 - x1 < minimum or y2 - y1 < minimum:
        return None
    return x1, y1, x2, y2


def read_image_bgr(image_path: str):
    """Non-ASCII-safe image read (cv2.imread fails on Chinese paths)."""
    import cv2
    import numpy as np

    data = np.fromfile(image_path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _unwrap(raw) -> list:
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], list):
        return raw[0]
    return raw if isinstance(raw, list) else []


def _jsonable(lines: list) -> list:
    result = []
    for line in lines or []:
        try:
            quad = [[float(p[0]), float(p[1])] for p in line[0]]
            text, confidence = line[1][0], float(line[1][1])
        except (TypeError, ValueError, IndexError):
            continue
        result.append([quad, [str(text), confidence]])
    return result


def main() -> int:
    request = json.loads(sys.stdin.read())
    image = read_image_bgr(request["image_path"])
    if image is None:
        print(json.dumps({"error": "IMAGE_UNREADABLE", "full": [], "crops": []}))
        return 0

    # paddle 2.6 protos need the pure-python protobuf parser with protobuf>=4
    os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
    from paddleocr import PaddleOCR

    engine = PaddleOCR(
        use_angle_cls=True, lang=request.get("lang", "ch"), show_log=False
    )

    response = {"full": _jsonable(_unwrap(engine.ocr(image, cls=True))), "crops": []}
    height, width = image.shape[:2]
    for rect in request.get("crops", []):
        bounds = clamp_rect(rect, width, height)
        if bounds is None:
            response["crops"].append([])
            continue
        x1, y1, x2, y2 = bounds
        try:
            crop_lines = _unwrap(engine.ocr(image[y1:y2, x1:x2], cls=True))
        except Exception:  # one bad crop must not kill the whole request
            crop_lines = []
        response["crops"].append(_jsonable(crop_lines))

    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
