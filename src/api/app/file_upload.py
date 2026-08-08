"""
HCT-104: Secure file upload, validation, storage and deletion propagation.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, UploadFile, status

from app.config import get_settings

logger = logging.getLogger(__name__)

MAGIC_BYTES: dict[str, list[bytes]] = {
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".pdf": [b"%PDF"],
    ".mp4": [b"\x00\x00\x00\x18ftyp", b"\x00\x00\x00\x20ftyp"],
    ".mov": [b"\x00\x00\x00\x14ftyp", b"\x00\x00\x00\x18ftyp"],
}

BUF_SIZE = 8192
MAX_FILENAME = 255
HASH_ALGO = "sha256"


def validate_filename(filename: str) -> str:
    """Reject path traversal and dangerous characters in filename."""
    name = Path(filename).name  # strip directory components
    if not name or name != filename or name.startswith("."):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="UPLOAD_FILENAME_INVALID",
        )
    if len(name) > MAX_FILENAME:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="UPLOAD_FILENAME_TOO_LONG",
        )
    return name


def validate_extension(filename: str) -> str:
    """Check extension against the allowed list."""
    settings = get_settings()
    ext = Path(filename).suffix.lower()
    if ext not in settings.upload_allowed_ext_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="UPLOAD_TYPE_NOT_ALLOWED",
        )
    return ext


def validate_magic(file: BinaryIO, ext: str, max_read: int = BUF_SIZE) -> None:
    """Check file magic bytes match the claimed extension."""
    expected = MAGIC_BYTES.get(ext)
    if not expected:
        return  # unknown magic list → skip
    start = file.read(max_read)
    file.seek(0)
    if not any(start.startswith(m) for m in expected):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="UPLOAD_MAGIC_MISMATCH",
        )


def validate_size(file: BinaryIO, max_bytes: int | None = None) -> int:
    """Measure file size; reject if exceeds limit."""
    settings = get_settings()
    limit = max_bytes if max_bytes is not None else settings.max_upload_bytes
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="UPLOAD_TOO_LARGE",
        )
    return size


def compute_hash(file: BinaryIO, algo: str = HASH_ALGO) -> str:
    """Compute the hash of a file's content."""
    hasher = hashlib.new(algo)
    file.seek(0)
    while True:
        chunk = file.read(BUF_SIZE)
        if not chunk:
            break
        hasher.update(chunk)
    file.seek(0)
    return hasher.hexdigest()


def random_storage_key(ext: str) -> str:
    """Generate an unguessable storage key with the original extension."""
    token = secrets.token_hex(32)
    return f"{token}{ext}"


def store_file(file: BinaryIO, storage_key: str) -> Path:
    """Write *file* to the controlled upload directory. Returns absolute path."""
    settings = get_settings()
    root = Path(settings.file_root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    dest = (root / storage_key).resolve()
    if not str(dest).startswith(str(root)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="UPLOAD_PATH_TRAVERSAL",
        )

    file.seek(0)
    with open(dest, "wb") as out:
        while True:
            chunk = file.read(BUF_SIZE)
            if not chunk:
                break
            out.write(chunk)
    return dest


def delete_file_tree(storage_key: str) -> list[str]:
    """Delete file + thumbnail + cache + index for *storage_key*. Returns deleted paths."""
    settings = get_settings()
    root = Path(settings.file_root).resolve()
    deleted: list[str] = []

    for subdir in ["", "thumbnails", "cache", "index"]:
        target = (root / subdir / storage_key).resolve()
        if str(target).startswith(str(root)) and target.exists():
            target.unlink(missing_ok=True)
            deleted.append(str(target))

    return deleted


async def validate_and_store(upload: UploadFile) -> dict:
    """Full upload pipeline: validate → store → return metadata."""
    filename = validate_filename(upload.filename or "unknown")
    ext = validate_extension(filename)
    validate_magic(upload.file, ext)
    size = validate_size(upload.file)
    file_hash = compute_hash(upload.file)
    storage_key = random_storage_key(ext)
    dest = store_file(upload.file, storage_key)

    logger.info(
        "UPLOAD_OK key=%s size=%d hash=%s ext=%s",
        storage_key, size, file_hash[:16], ext,
    )
    return {
        "original_name": filename,
        "storage_key": storage_key,
        "size_bytes": size,
        "hash_algo": HASH_ALGO,
        "hash": file_hash,
        "extension": ext,
        "path": str(dest),
    }
