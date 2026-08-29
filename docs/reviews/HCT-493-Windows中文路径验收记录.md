# HCT-493 Windows 中文路径验收记录

- Issue: #555
- Story: HCT-493
- FR/NFR: FR-01, NFR-01, NFR-02, NFR-03, NFR-07
- Status: Blocked
- Date: 2026-08-29
- Baseline: `fd8cc1be110388dcda9cc4746ec32bb9b5b0046a`

## Scope

Verify that the local YuNet and SFace ONNX models can be loaded when the
repository path contains Chinese characters, without exposing a local path in
authentication errors. This record intentionally contains no face image,
template, PIN, token, account, or camera recording.

## Automated Evidence

The repository is located at `D:\xuexi\2026暑期企业实训\前端\issedu_ysu2026_3709`,
which exercises a Chinese Windows path. The local runtime used Python 3.11.15
and OpenCV 4.14.0.

```text
.\\.venv\\Scripts\\python.exe -m pytest \
  tests/unit/test_hct424_face_model_unicode_path.py \
  tests/contract/test_hct424_face_onnx_error_contract.py -q

s....s...
```

The passing cases cover byte-buffer model loading, corrupt or missing model
handling, and stable 503 contracts that do not expose an ONNX path or OpenCV
implementation detail. Two inference cases were skipped because the required
ONNX weights are absent on this machine.

## Manual Acceptance Status

| Required path | Result | Evidence |
|---|---|---|
| Register a face credential | Not run | YuNet/SFace weights unavailable |
| Face login | Not run | YuNet/SFace weights unavailable |
| View credential list | Not run | Registration prerequisite not met |

## Blocker

`scripts/ensure_face_models.py` was run on this Windows machine. Downloading
the first model from OpenCV Zoo failed with `ssl.SSLEOFError`, which the
application correctly converted to `FACE_DETECTOR_UNAVAILABLE`. No model
weight was retained locally and no biometric sample was collected.

To continue, place the approved YuNet and SFace ONNX files in `models/face/`
or restore network access to the model source, then run the three manual paths
using an authorized demo participant. Record only pass/fail outcomes and
non-sensitive failure categories. Do not add images, embeddings, PINs, session
tokens, or full local paths to this record.

## Rollback

This change is documentation only. Revert this file if the recorded command
results are superseded by a completed manual acceptance run.
