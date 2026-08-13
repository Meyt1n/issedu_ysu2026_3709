"""Isolated YOLO box-assist worker process.

Torch cannot share a Windows process with PaddlePaddle (DLL conflicts), and
co-residency with other heavy runtimes has produced native crashes under
memory pressure, so the adapter runs YOLO here: a short-lived process that
detects, prints JSON and exits before the OCR worker starts.

Two backends, chosen by the weights suffix:

* ``.onnx`` — pure onnxruntime + OpenCV (no torch at all).  Preferred: it
  stays stable even while a training job saturates the machine, because
  torch's DLL initialisation is exactly what breaks under that contention.
* ``.pt`` — ultralytics/torch fallback for environments without the
  exported artifact.

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

INPUT_SIZE = 640
NMS_IOU = 0.45


def read_image_bgr(image_path: str):
    """Non-ASCII-safe image read (cv2.imread fails on Chinese paths)."""
    import cv2
    import numpy as np

    data = np.fromfile(image_path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def detect_onnx(request: dict) -> list[dict]:
    """YOLO11 single-class detection with onnxruntime only (no torch)."""
    import cv2
    import numpy as np
    import onnxruntime as ort

    image = read_image_bgr(request["image_path"])
    if image is None:
        return []
    height, width = image.shape[:2]
    ratio = min(INPUT_SIZE / width, INPUT_SIZE / height)
    new_w, new_h = round(width * ratio), round(height * ratio)
    pad_x, pad_y = (INPUT_SIZE - new_w) // 2, (INPUT_SIZE - new_h) // 2
    canvas = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = cv2.resize(
        image, (new_w, new_h)
    )
    blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(
        request["weights"], sess_options=options, providers=["CPUExecutionProvider"]
    )
    output = session.run(None, {session.get_inputs()[0].name: blob})[0]
    predictions = output[0].T  # (8400, 4+classes): cx, cy, w, h, score(s)
    scores = predictions[:, 4:].max(axis=1)
    conf = float(request.get("conf", 0.25))
    keep = scores >= conf
    predictions, scores = predictions[keep], scores[keep]
    if not len(predictions):
        return []

    # letterbox space -> original pixel space
    boxes_xywh = []
    for cx, cy, box_w, box_h in predictions[:, :4]:
        x1 = (cx - box_w / 2 - pad_x) / ratio
        y1 = (cy - box_h / 2 - pad_y) / ratio
        boxes_xywh.append([x1, y1, box_w / ratio, box_h / ratio])
    indices = cv2.dnn.NMSBoxes(boxes_xywh, scores.tolist(), conf, NMS_IOU)
    boxes: list[dict] = []
    for index in np.array(indices).flatten():
        x1, y1, box_w, box_h = boxes_xywh[int(index)]
        x1_clamped = min(max(x1, 0.0), width - 1.0)
        y1_clamped = min(max(y1, 0.0), height - 1.0)
        boxes.append(
            {
                "x": x1_clamped,
                "y": y1_clamped,
                "width": max(min(box_w, width - x1_clamped), 1e-3),
                "height": max(min(box_h, height - y1_clamped), 1e-3),
                "confidence": min(max(float(scores[int(index)]), 0.0), 1.0),
            }
        )
    boxes.sort(key=lambda item: -item["confidence"])
    return boxes


def detect_torch(request: dict) -> list[dict]:
    import torch

    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "2")))
    from ultralytics import YOLO

    model = YOLO(request["weights"])
    result = model.predict(
        source=request["image_path"],
        conf=float(request.get("conf", 0.25)),
        device=request.get("device", "cpu"),
        verbose=False,
    )[0]
    boxes: list[dict] = []
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
    return boxes


def main() -> int:
    request = json.loads(sys.stdin.read())

    # keep thread pools small: the box-assist model is tiny and the machine
    # may be running a training job on all cores at the same time
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("MKL_NUM_THREADS", "2")

    if str(request["weights"]).lower().endswith(".onnx"):
        boxes = detect_onnx(request)
    else:
        boxes = detect_torch(request)
    print(json.dumps({"boxes": boxes}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
