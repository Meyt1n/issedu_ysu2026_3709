"""
HCT-104: Secure file upload tests.
"""

import io
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.config import get_settings
from app.file_upload import (
    compute_hash,
    delete_file_tree,
    random_storage_key,
    store_file,
    validate_and_store,
    validate_extension,
    validate_filename,
    validate_magic,
    validate_size,
)


class TestValidateFilename:
    def test_normal_name_ok(self):
        assert validate_filename("report.pdf") == "report.pdf"

    def test_path_traversal_rejected(self):
        with pytest.raises(Exception) as exc:
            validate_filename("../etc/passwd")
        assert "FILENAME" in str(exc.value.detail)

    def test_empty_rejected(self):
        with pytest.raises(Exception):
            validate_filename("")

    def test_dotfile_rejected(self):
        with pytest.raises(Exception):
            validate_filename(".hidden")


class TestValidateExtension:
    def test_allowed_ext_ok(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "upload_allowed_extensions", ".jpg,.pdf")
        assert validate_extension("photo.jpg") == ".jpg"
        assert validate_extension("doc.pdf") == ".pdf"

    def test_disallowed_ext_rejected(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "upload_allowed_extensions", ".jpg,.pdf")
        with pytest.raises(Exception) as exc:
            validate_extension("script.exe")
        assert "NOT_ALLOWED" in str(exc.value.detail)


class TestValidateMagic:
    def test_jpeg_magic_ok(self):
        file = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF")
        validate_magic(file, ".jpg")

    def test_png_magic_ok(self):
        file = io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
        validate_magic(file, ".png")

    def test_magic_mismatch_rejected(self):
        file = io.BytesIO(b"#!/bin/bash\necho pwned")
        with pytest.raises(Exception) as exc:
            validate_magic(file, ".jpg")
        assert "MAGIC" in str(exc.value.detail)


class TestValidateSize:
    def test_within_limit_ok(self):
        file = io.BytesIO(b"a" * 100)
        size = validate_size(file, max_bytes=1024)
        assert size == 100

    def test_exceeds_limit_rejected(self):
        file = io.BytesIO(b"a" * 2000)
        with pytest.raises(Exception):
            validate_size(file, max_bytes=1024)


class TestComputeHash:
    def test_hash_deterministic(self):
        file = io.BytesIO(b"hello world")
        assert compute_hash(file) == compute_hash(io.BytesIO(b"hello world"))

    def test_hash_different(self):
        h1 = compute_hash(io.BytesIO(b"hello"))
        h2 = compute_hash(io.BytesIO(b"world"))
        assert h1 != h2


class TestStorage:
    def test_random_key_has_extension(self):
        key = random_storage_key(".jpg")
        assert key.endswith(".jpg")
        assert len(key) > 32

    def test_store_and_delete(self, monkeypatch, tmp_path):
        settings = get_settings()
        monkeypatch.setattr(settings, "file_root", str(tmp_path))

        file = io.BytesIO(b"test content")
        key = random_storage_key(".txt")
        dest = store_file(file, key)
        assert Path(dest).exists()
        assert Path(dest).read_bytes() == b"test content"

        deleted = delete_file_tree(key)
        assert not Path(dest).exists()
        assert len(deleted) > 0


class TestValidateAndStore:
    @pytest.mark.anyio
    async def test_successful_upload(self, monkeypatch, tmp_path):
        settings = get_settings()
        monkeypatch.setattr(settings, "file_root", str(tmp_path))
        monkeypatch.setattr(settings, "upload_allowed_extensions", ".jpg,.png,.pdf")

        content = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x00\x00\x00test jpeg content"
        )
        upload = UploadFile(
            filename="test.jpg",
            file=io.BytesIO(content),
            size=len(content),
        )
        result = await validate_and_store(upload)
        assert result["original_name"] == "test.jpg"
        assert result["extension"] == ".jpg"
        assert result["size_bytes"] == len(content)
        assert len(result["hash"]) == 64

        # Verify stored file
        stored = Path(result["path"])
        assert stored.exists()
        assert stored.read_bytes() == content
