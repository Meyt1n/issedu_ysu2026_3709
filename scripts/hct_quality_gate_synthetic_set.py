"""Generate the synthetic quality-gate test set (fully licensed, reproducible).

HCT-201 real test images are studio shots on white backgrounds and are all
rejected by the household quality gate (100% GLARE). Until an approved
household-captured set exists, this generator provides a controlled,
deterministic substitute for gate calibration, adapter integration tests and
regressions. Every image is drawn procedurally (no external photos, no
license risk) and targets exactly one gate behaviour.

Variants (per-seed):
  clean         -> PASS
  tilted        -> PASS (perspective tilt must not be over-rejected)
  blurry        -> BLURRY
  glare         -> GLARE
  dark          -> TOO_DARK
  bright        -> TOO_BRIGHT
  small_target  -> TARGET_TOO_SMALL
  cropped       -> SUBJECT_CROPPED

Usage:
  python scripts/hct_quality_gate_synthetic_set.py --output-dir <dir> [--per-variant 4]

The manifest records generator version, seed, per-image SHA-256, expected and
actual gate outcomes; generation fails if any expectation is violated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zlib
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from ai.vision.quality_gate import QualityThresholds, assess_image  # noqa: E402

GENERATOR_VERSION = "hct-quality-gate-synthetic-v1"
CANVAS = (960, 1280)  # h, w  (>= 640x480 gate minimum)

BOX_COLORS = [
    (170, 120, 40),  # blue-ish (BGR)
    (60, 140, 60),  # green
    (50, 90, 200),  # red-orange
    (140, 70, 130),  # purple
]

EXPECTATIONS = {
    "clean": {"decision": "PASS", "reasons": set()},
    "tilted": {"decision": "PASS", "reasons": set()},
    "blurry": {"decision": "RETAKE", "reasons": {"BLURRY"}},
    "glare": {"decision": "RETAKE", "reasons": {"GLARE"}},
    "dark": {"decision": "RETAKE", "reasons": {"TOO_DARK"}},
    "bright": {"decision": "RETAKE", "reasons": {"TOO_BRIGHT"}},
    "small_target": {"decision": "RETAKE", "reasons": {"TARGET_TOO_SMALL"}},
    "cropped": {"decision": "RETAKE", "reasons": {"SUBJECT_CROPPED"}},
}


def _background(rng: np.random.Generator, level: float = 120.0) -> np.ndarray:
    height, width = CANVAS
    vertical = np.linspace(-12, 12, height, dtype=np.float32)[:, None]
    horizontal = np.linspace(-8, 8, width, dtype=np.float32)[None, :]
    base = level + vertical + horizontal
    noise = rng.normal(0.0, 5.0, size=(height, width)).astype(np.float32)
    gray = np.clip(base + noise, 0, 255).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _draw_box(
    image: np.ndarray,
    rng: np.random.Generator,
    *,
    scale: float = 0.55,
    center: tuple[float, float] | None = None,
    color: tuple[int, int, int] | None = None,
) -> None:
    """Draw a synthetic medicine carton with text-like details."""
    height, width = image.shape[:2]
    box_w = int(width * scale)
    box_h = int(box_w * 0.62)
    cx, cy = center or (0.5, 0.52)
    x0 = int(width * cx - box_w / 2)
    y0 = int(height * cy - box_h / 2)
    x1, y1 = x0 + box_w, y0 + box_h
    color = color or BOX_COLORS[int(rng.integers(len(BOX_COLORS)))]

    cv2.rectangle(image, (x0, y0), (x1, y1), color, -1)
    cv2.rectangle(image, (x0, y0), (x1, y1), (30, 30, 30), max(3, box_w // 90))
    band_h = max(10, box_h // 5)
    cv2.rectangle(image, (x0, y0), (x1, y0 + band_h), (235, 235, 235), -1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    text_scale = box_w / 420.0
    cv2.putText(
        image, "DEMO MED A", (x0 + box_w // 12, y0 + band_h - band_h // 4),
        font, text_scale, (40, 40, 40), max(2, box_w // 200),
    )
    cv2.putText(
        image, "0.25g x 24", (x0 + box_w // 12, y0 + band_h + box_h // 4),
        font, text_scale * 0.9, (245, 245, 245), max(2, box_w // 220),
    )
    cv2.putText(
        image, "LOT A12345  EXP 2027-05", (x0 + box_w // 12, y0 + band_h + box_h // 2),
        font, text_scale * 0.62, (235, 235, 235), max(1, box_w // 280),
    )
    # barcode-like stripes
    stripe_x = x0 + box_w // 12
    stripe_y = y1 - box_h // 5
    stripe_h = box_h // 7
    while stripe_x < x0 + box_w // 2:
        stripe_w = int(rng.integers(2, 7))
        cv2.rectangle(
            image, (stripe_x, stripe_y), (stripe_x + stripe_w, stripe_y + stripe_h),
            (20, 20, 20), -1,
        )
        stripe_x += stripe_w + int(rng.integers(2, 6))


def _render(variant: str, rng: np.random.Generator) -> np.ndarray:
    if variant == "dark":
        image = _background(rng, level=26.0)
        _draw_box(image, rng)
        image = np.clip(image.astype(np.float32) * 0.28, 0, 255).astype(np.uint8)
        return image
    if variant == "bright":
        image = _background(rng, level=228.0)
        _draw_box(image, rng)
        image = np.clip(image.astype(np.float32) * 1.12 + 30, 0, 255).astype(np.uint8)
        return image

    image = _background(rng)
    if variant == "small_target":
        # Extra texture keeps global edge density above the NO_TARGET floor so
        # the specific TARGET_TOO_SMALL reason fires (subject ratio < 0.08).
        extra = rng.normal(0.0, 6.0, size=image.shape[:2]).astype(np.float32)
        image = np.clip(image.astype(np.float32) + extra[..., None], 0, 255).astype(
            np.uint8
        )
        _draw_box(image, rng, scale=0.22, center=(0.5, 0.5))
        return image
    if variant == "cropped":
        # Tall carton touching top, bottom and left edges: subject stays the
        # dominant contour but 3/4 borders are hit (ratio 0.75 > 0.50).
        # Background texture and stripes keep edge density above NO_TARGET.
        extra = rng.normal(0.0, 6.0, size=image.shape[:2]).astype(np.float32)
        image = np.clip(image.astype(np.float32) + extra[..., None], 0, 255).astype(
            np.uint8
        )
        height, width = image.shape[:2]
        color = BOX_COLORS[int(rng.integers(len(BOX_COLORS)))]
        # Fully inside the frame but flush with top/left/bottom margins so the
        # contour stays closed while 3/4 borders count as touched.
        x0, y0 = 4, 4
        x1, y1 = int(width * 0.62), height - 4
        cv2.rectangle(image, (x0, y0), (x1, y1), color, -1)
        cv2.rectangle(image, (x0, y0), (x1, y1), (30, 30, 30), 8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(image, "DEMO MED A", (40, height // 4), font, 1.6, (240, 240, 240), 4)
        cv2.putText(image, "0.25g x 24", (40, height // 2), font, 1.3, (240, 240, 240), 3)
        cv2.putText(
            image, "LOT A12345", (40, int(height * 0.72)), font, 1.1, (235, 235, 235), 3
        )
        stripe_x, stripe_y = 40, int(height * 0.82)
        while stripe_x < int(width * 0.4):
            stripe_w = int(rng.integers(3, 8))
            cv2.rectangle(
                image, (stripe_x, stripe_y), (stripe_x + stripe_w, stripe_y + 70),
                (20, 20, 20), -1,
            )
            stripe_x += stripe_w + int(rng.integers(3, 7))
        return image

    _draw_box(image, rng)
    if variant == "tilted":
        height, width = image.shape[:2]
        shift = width * 0.12
        source = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
        target = np.float32(
            [[shift, 18], [width - shift * 0.4, 0], [width, height - 24], [0, height]]
        )
        matrix = cv2.getPerspectiveTransform(source, target)
        image = cv2.warpPerspective(
            image, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE
        )
        return image
    if variant == "blurry":
        return cv2.GaussianBlur(image, (0, 0), sigmaX=6.5)
    if variant == "glare":
        height, width = image.shape[:2]
        overlay = image.copy()
        cv2.ellipse(
            overlay,
            (int(width * 0.52), int(height * 0.45)),
            (int(width * 0.34), int(height * 0.30)),
            18, 0, 360, (255, 255, 255), -1,
        )
        cv2.ellipse(
            overlay,
            (int(width * 0.2), int(height * 0.75)),
            (int(width * 0.16), int(height * 0.12)),
            -12, 0, 360, (254, 254, 254), -1,
        )
        return overlay
    return image


def generate(output_dir: Path, *, per_variant: int = 4, seed: int = 20260813) -> dict:
    """Generate the set, self-check every expectation and write the manifest."""
    thresholds = QualityThresholds()
    out = output_dir
    out.mkdir(parents=True, exist_ok=True)
    records = []
    failures = []
    for variant, expected in EXPECTATIONS.items():
        for index in range(per_variant):
            # zlib.crc32 keeps the per-image seed deterministic across runs
            # (str hash() is randomized per process and broke reproducibility).
            variant_key = zlib.crc32(variant.encode("utf-8")) % 10_000
            rng = np.random.default_rng(seed + variant_key + index)
            image = _render(variant, rng)
            name = f"gate-{variant}-{index:02d}.png"
            ok, encoded = cv2.imencode(".png", image)
            if not ok:
                raise SystemExit(f"encode failed: {name}")
            payload = encoded.tobytes()
            (out / name).write_bytes(payload)

            report = assess_image(image, source_id=name, thresholds=thresholds)
            actual_reasons = set(report["reasons"])
            expected_ok = report["decision"] == expected["decision"] and expected[
                "reasons"
            ] <= actual_reasons
            if expected["decision"] == "PASS":
                expected_ok = report["decision"] == "PASS"
            if not expected_ok:
                failures.append(
                    {"image": name, "expected": expected["decision"],
                     "expected_reasons": sorted(expected["reasons"]),
                     "actual": report["decision"], "actual_reasons": sorted(actual_reasons)}
                )
            records.append(
                {
                    "image": name,
                    "variant": variant,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "expected_decision": expected["decision"],
                    "expected_reasons": sorted(expected["reasons"]),
                    "actual_decision": report["decision"],
                    "actual_reasons": sorted(actual_reasons),
                }
            )

    manifest = {
        "schema_version": "hct-quality-gate-synthetic-set/v1",
        "generator_version": GENERATOR_VERSION,
        "generator": "scripts/hct_quality_gate_synthetic_set.py",
        "seed": seed,
        "per_variant": per_variant,
        "canvas": {"height": CANVAS[0], "width": CANVAS[1]},
        "thresholds_config": thresholds.config_version,
        "license": "synthetic, generated by this repository; no external photos",
        "purpose": "quality-gate calibration/regression and adapter integration demos",
        "not_for": "model training or accuracy claims about real photos",
        "images": records,
        "expectation_failures": failures,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--per-variant", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260813)
    args = parser.parse_args()

    manifest = generate(args.output_dir, per_variant=args.per_variant, seed=args.seed)
    failures = manifest["expectation_failures"]
    summary = {
        "images": len(manifest["images"]),
        "expectation_failures": len(failures),
        "output": str(args.output_dir),
    }
    print(json.dumps(summary, ensure_ascii=False))
    if failures:
        print(json.dumps(failures[:8], ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
