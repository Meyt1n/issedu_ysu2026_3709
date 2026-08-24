"""Resident vision worker: polls queued vision tasks and processes them.

Runs inside the family trusted domain, next to the API. The web UI only
performs the quality gate, uploads the image and creates a vision task;
this worker picks up ``queued`` tasks for the configured actors, downloads
the original image, runs the local engines (PaddleOCR full-image OCR,
optional YOLO box assist, OpenCV barcode decoding, rule/LLM field
proposals) and submits signed evidence. The server then fuses candidates
and bridges the result into a human review task — the worker never
confirms anything by itself.

Example:
    python scripts/vision_worker.py --actors <your-actor-id> \
        --api http://127.0.0.1:8000/api/v1 --interval 5

Environment: same as scripts/run_local_adapter.py (HCT_VISION_WORKER_PYTHON,
HCT_MASTER_DATA_VERSION, HCT_OCR_LANG, HCT_ADAPTER_SIGNING_KEY ...).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import cv2

REPO_ROOT = Path(__file__).resolve().parents[1]
for entry in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import requests  # noqa: E402
from ai.vision.evidence_pipeline import issue_adapter_receipt  # noqa: E402
from ai.vision.local_models import (  # noqa: E402
    QwenLoraFieldExtractor,
    YoloBoxAssist,
)
from ai.vision.local_ocr import (  # noqa: E402
    LocalBarcodeDecoder,
    LocalPaddleOCR,
)
from ai.vision.video_frames import (  # noqa: E402
    decode_video_frames,
    merge_frame_requests,
)

from run_local_adapter import build_request  # noqa: E402

SUFFIX_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-quicktime": ".mov",
}


def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


class Worker:
    def __init__(
        self,
        api: str,
        actors: list[str],
        signing_key: str,
        *,
        video_sample_interval_ms: int = 1000,
        video_max_frames: int = 8,
    ) -> None:
        self.api = api.rstrip("/")
        self.actors = actors
        self.signing_key = signing_key
        self.video_sample_interval_ms = video_sample_interval_ms
        self.video_max_frames = video_max_frames
        self.http = requests.Session()
        self.http.trust_env = False  # ignore system proxies for localhost calls
        # Polling is sparse; uvicorn drops idle keep-alive sockets which makes
        # reused connections fail with RemoteDisconnected. Use short-lived
        # connections instead.
        self.http.headers["Connection"] = "close"
        self.failures: dict[str, int] = {}
        log("loading local engines (first run may download PaddleOCR weights)...")
        self.yolo = YoloBoxAssist()
        self.extractor = QwenLoraFieldExtractor()
        self.ocr = LocalPaddleOCR()
        self.barcode = LocalBarcodeDecoder()
        log(
            "engines ready: "
            + json.dumps(
                {
                    "yolo": self.yolo.available,
                    "ocr": self.ocr.available,
                    "barcode": self.barcode.available,
                    "llm": self.extractor.available,
                },
                ensure_ascii=False,
            )
        )

    def poll_once(self) -> int:
        processed = 0
        for actor in self.actors:
            try:
                response = self.http.get(
                    f"{self.api}/vision-tasks",
                    params={"task_status": "queued", "limit": 10},
                    headers={"X-Actor-ID": actor},
                    timeout=30,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                log(f"poll failed for {actor}: {exc}")
                continue
            for task in response.json():
                task_id = task["id"]
                if self.failures.get(task_id, 0) >= 3:
                    continue
                try:
                    self.process(actor, task)
                    processed += 1
                    self.failures.pop(task_id, None)
                except Exception as exc:  # keep the loop alive per task
                    self.failures[task_id] = self.failures.get(task_id, 0) + 1
                    log(f"task {task_id[:8]} failed ({self.failures[task_id]}/3): {exc}")
        return processed

    def _run_video_engines(self, media_path: Path, run_id: str):
        """HCT-414-D2: sample frames, run the engines per frame, merge once."""
        frames = decode_video_frames(
            media_path,
            sample_interval_ms=self.video_sample_interval_ms,
            max_frames=self.video_max_frames,
        )
        frame_requests = []
        with tempfile.TemporaryDirectory() as frame_dir:
            for position, frame in enumerate(frames):
                frame_path = Path(frame_dir) / f"frame-{position:02d}.png"
                cv2.imwrite(str(frame_path), frame.image)
                frame_requests.append(
                    build_request(
                        yolo=self.yolo,
                        extractor=self.extractor,
                        image=frame_path,
                        ocr_rows=[],
                        barcode_rows=[],
                        run_id=f"{run_id}-f{position + 1}",
                        local_ocr=self.ocr,
                        local_barcode=self.barcode,
                    )
                )
        log(
            f"video frames processed={len(frame_requests)} "
            f"(interval={self.video_sample_interval_ms}ms cap={self.video_max_frames})"
        )
        return merge_frame_requests(frame_requests, run_id=f"{run_id}-video")

    def process(self, actor: str, task: dict) -> None:
        task_id = task["id"]
        headers = {"X-Actor-ID": actor}
        media_type = task.get("media_type", "image")
        log(
            f"task {task_id[:8]} ({actor}): downloading {media_type} "
            f"{task['file_id'][:16]}..."
        )
        download = self.http.get(
            f"{self.api}/files/{task['file_id']}", headers=headers, timeout=60
        )
        download.raise_for_status()
        suffix = SUFFIX_BY_MIME.get(
            download.headers.get("content-type", "").split(";")[0].strip(),
            ".mp4" if media_type == "video" else ".jpg",
        )

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(download.content)
            media_path = Path(handle.name)
        try:
            log(f"task {task_id[:8]}: running local engines...")
            run_id = f"worker-{os.getpid()}-{task_id[:8]}"
            if media_type == "video":
                request = self._run_video_engines(media_path, run_id)
            else:
                request = build_request(
                    yolo=self.yolo,
                    extractor=self.extractor,
                    image=media_path,
                    ocr_rows=[],
                    barcode_rows=[],
                    run_id=run_id,
                    local_ocr=self.ocr,
                    local_barcode=self.barcode,
                )
        finally:
            media_path.unlink(missing_ok=True)

        receipt = issue_adapter_receipt(
            task_id, task.get("input_digest") or "", request, self.signing_key
        )
        payload = json.loads(request.model_dump_json())
        payload["adapter_receipt"] = receipt

        evidence = self.http.post(
            f"{self.api}/vision-tasks/{task_id}/evidence",
            json=payload,
            headers=headers,
            timeout=300,
        )
        evidence.raise_for_status()
        body = evidence.json()
        log(
            f"task {task_id[:8]}: done, fusion_readiness={body['fusion_readiness']}, "
            f"fields={len(body['fields'])}, ocr_tokens={len(request.ocr_tokens)}, "
            f"barcodes={len(request.barcodes)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api", default=os.environ.get("HCT_API_BASE", "http://127.0.0.1:8000/api/v1")
    )
    parser.add_argument(
        "--actors",
        default=os.environ.get("HCT_WORKER_ACTORS", "demo-parent"),
        help="comma separated actor ids whose queued tasks this worker serves",
    )
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true", help="single poll pass then exit")
    parser.add_argument(
        "--video-sample-interval-ms",
        type=int,
        default=1000,
        help="sampling interval between video frames fed to the local engines",
    )
    parser.add_argument(
        "--video-max-frames",
        type=int,
        default=8,
        help="upper bound of sampled frames processed per video task",
    )
    args = parser.parse_args()

    actors = [item.strip() for item in args.actors.split(",") if item.strip()]
    if not actors:
        raise SystemExit("no actors configured")
    signing_key = os.environ.get("HCT_ADAPTER_SIGNING_KEY", "dev-only-change-me")

    worker = Worker(
        args.api,
        actors,
        signing_key,
        video_sample_interval_ms=args.video_sample_interval_ms,
        video_max_frames=args.video_max_frames,
    )
    log(f"watching queued tasks for actors={actors} api={args.api}")
    while True:
        processed = worker.poll_once()
        if args.once:
            log(f"single pass complete, processed={processed}")
            return 0
        time.sleep(args.interval if processed == 0 else 0.5)


if __name__ == "__main__":
    raise SystemExit(main())
