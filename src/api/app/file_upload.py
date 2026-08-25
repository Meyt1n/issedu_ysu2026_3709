"""
HCT-104: Secure file upload, validation, storage and deletion propagation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, UploadFile, status

from app.config import get_settings

logger = logging.getLogger(__name__)

# Server-side ownership sidecars live in a reserved subdirectory of the file
# root.  Storage keys are 64 hex chars plus an extension, so they can never
# collide with this directory name.
OWNER_META_DIR = "meta"

MAGIC_BYTES: dict[str, list[bytes]] = {
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".pdf": [b"%PDF"],
}

# ISO-BMFF containers (mp4/mov) open with a 4-byte big-endian box size
# followed by the "ftyp" brand box.  The size varies across recorder vendors
# and OpenCV's own writer, so a fixed-prefix list would reject valid files;
# HCT-414-D2 validates the structure instead.
FTYP_EXTENSIONS = frozenset({".mp4", ".mov"})


def _has_ftyp_magic(start: bytes) -> bool:
    if len(start) < 8 or start[4:8] != b"ftyp":
        return False
    box_size = int.from_bytes(start[:4], "big")
    return 8 <= box_size <= 256

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
    start = file.read(max_read)
    file.seek(0)
    if ext in FTYP_EXTENSIONS:
        if not _has_ftyp_magic(start):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="UPLOAD_MAGIC_MISMATCH",
            )
        return
    expected = MAGIC_BYTES.get(ext)
    if not expected:
        return  # unknown magic list → skip
    if not any(start.startswith(m) for m in expected):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="UPLOAD_MAGIC_MISMATCH",
        )


def validate_size(file: BinaryIO, max_bytes: int | None = None) -> int:
    """Measure file size; reject empty files and files exceeding the limit."""
    settings = get_settings()
    limit = max_bytes if max_bytes is not None else settings.max_upload_bytes
    file.seek(0, 2)  # SEEK_END
    size = file.tell()
    file.seek(0)
    if size == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="UPLOAD_EMPTY",
        )
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
    # ``is_relative_to`` is the strict containment check; a plain string
    # prefix test would accept sibling directories such as ``<root>-evil``.
    if not dest.is_relative_to(root):
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


def record_file_owner(storage_key: str, actor_id: str) -> None:
    """Persist the uploading actor so later reads/deletes can be scoped."""
    settings = get_settings()
    root = Path(settings.file_root).resolve()
    meta_dir = root / OWNER_META_DIR
    meta_dir.mkdir(parents=True, exist_ok=True)
    target = (meta_dir / storage_key).resolve()
    if not target.is_relative_to(meta_dir):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="UPLOAD_PATH_TRAVERSAL",
        )
    target.write_text(json.dumps({"owner": actor_id}), encoding="utf-8")


def file_owner(storage_key: str) -> str | None:
    """Return the recorded uploader, or None for legacy files without metadata."""
    settings = get_settings()
    meta_dir = Path(settings.file_root).resolve() / OWNER_META_DIR
    target = (meta_dir / storage_key).resolve()
    if not target.is_relative_to(meta_dir) or not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    owner = data.get("owner")
    return owner if isinstance(owner, str) and owner else None


def delete_file_tree(storage_key: str) -> list[str]:
    """Delete file + thumbnail + cache + index + owner metadata for *storage_key*."""
    settings = get_settings()
    root = Path(settings.file_root).resolve()
    deleted: list[str] = []

    for subdir in ["", "thumbnails", "cache", "index", OWNER_META_DIR]:
        target = (root / subdir / storage_key).resolve()
        if target.is_relative_to(root) and target.exists():
            target.unlink(missing_ok=True)
            deleted.append(str(target))

    return deleted


async def validate_and_store(upload: UploadFile, owner: str | None = None) -> dict:
    """Full upload pipeline: validate → store → return metadata."""
    filename = validate_filename(upload.filename or "unknown")
    ext = validate_extension(filename)
    # Size first: an empty body should deterministically report UPLOAD_EMPTY
    # for every allowed extension instead of an incidental magic mismatch.
    size = validate_size(upload.file)
    validate_magic(upload.file, ext)
    file_hash = compute_hash(upload.file)
    storage_key = random_storage_key(ext)
    store_file(upload.file, storage_key)
    if owner is not None:
        record_file_owner(storage_key, owner)

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
    }
