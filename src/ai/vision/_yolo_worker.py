"""Isolated YOLO box-assist worker process.

Torch cannot share a Windows process with PaddlePaddle (DLL conflicts), and
co-residency with other heavy runtimes has produced native crashes under
memory pressure, so the adapter runs YOLO here: a short-lived process that
imports torch, detects, prints JSON and exits before the OCR worker starts.

Protocol: a JSON request on stdin ->

    {"image_path": "...", "weights": "...", "device": "cpu", "conf": 0.25}

and a JSON response on stdout ->

    {"boxes": [{"x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0,
                "confidence": 0.9}, ...]}

All logs go to stderr; stdout carries exactly one JSON document.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    request = json.loads(sys.stdin.read())

    # keep thread pools small: the box-assist model is tiny and the machine
    # may be running a training job on all cores at the same time
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("MKL_NUM_THREADS", "2")

    import torch

    torch.set_num_threads(int(os.environ["OMP_NUM_THREADS"]))
    from ultralytics import YOLO

    model = YOLO(request["weights"])
    result = model.predict(
        source=request["image_path"],
        conf=float(request.get("conf", 0.25)),
        device=request.get("device", "cpu"),
        verbose=False,
    )[0]

    boxes = []
    raw = getattr(result, "boxes", None)
    if raw is not None:
        for index in range(len(raw)):
            x1, y1, x2, y2 = (float(v) for v in raw.xyxy[index].tolist())
            boxes.append(
                {
                    "x": max(x1, 0.0),
                    "y": max(y1, 0.0),
                    "width": max(x2 - x1, 1e-3),
                    "height": max(y2 - y1, 1e-3),
                    "confidence": min(max(float(raw.conf[index]), 0.0), 1.0),
                }
            )
    print(json.dumps({"boxes": boxes}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
