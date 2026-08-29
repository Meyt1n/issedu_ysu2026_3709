# HCT-493 Windows 中文路径验收记录

- Issue: #555
- Story: HCT-493
- FR/NFR: FR-01, NFR-01, NFR-02, NFR-03, NFR-07
- Status: Complete
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

The passing cases cover byte-buffer model loading, real YuNet/SFace model
loading from a Unicode directory, corrupt or missing model handling, and
stable 503 contracts that do not expose an ONNX path or OpenCV implementation
detail. All cases ran after the approved weights were copied locally.

The weights are local, are ignored by Git, and are not included in this PR:

```text
models/face/face_detection_yunet_2023mar.onnx       232589 bytes
models/face/face_recognition_sface_2021dec.onnx   38696353 bytes
```

## Manual Acceptance Status

| Required path | Result | Evidence |
|---|---|---|
| Register a face credential | Pass | User completed the flow in the local Windows demo |
| Face login | Pass | User completed the flow in the local Windows demo |
| View credential list | Pass | Screenshot shows the registered member with an active/有效 credential |

## Blocker

The first model download from OpenCV Zoo failed with `ssl.SSLEOFError`; the
approved weights were subsequently copied into `models/face/` without adding
them to Git. `scripts/ensure_face_models.py` now succeeds, the full
Unicode-path regression passes, and the user completed the three manual
acceptance paths in the local Windows demo. No biometric sample was collected
in the repository.

The manual acceptance is complete for this demo environment. Future changes
to the model, camera pipeline, or threshold require a new acceptance run.
Do not add images, embeddings, PINs, session tokens, or full local paths to
this record.

## Rollback

This change is documentation only. Revert this file if the recorded command
results are superseded by a completed manual acceptance run.
