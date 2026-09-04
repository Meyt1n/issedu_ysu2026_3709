from __future__ import annotations

import io
import zipfile

import pytest
from fastapi import HTTPException, UploadFile

from app.file_extract import extract_uploaded_file


def _upload(name: str, content: bytes, media_type: str = "application/octet-stream") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=name,
        headers={"content-type": media_type},
    )


def test_text_attachment_is_extracted_without_persistence() -> None:
    result = extract_uploaded_file(_upload("notes.txt", "用药记录\n仅供复核".encode()))

    assert result["file_name"] == "notes.txt"
    assert result["text"] == "用药记录\n仅供复核"
    assert result["extractor"] == "utf8-or-gb18030"
    assert result["cloud_used"] is False


def test_docx_attachment_extracts_document_xml() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<?xml version='1.0' encoding='UTF-8'?>
            <w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
              <w:body><w:p><w:r><w:t>阿莫西林胶囊</w:t></w:r></w:p></w:body>
            </w:document>""",
        )

    result = extract_uploaded_file(_upload("label.docx", buffer.getvalue()))

    assert result["text"] == "阿莫西林胶囊"
    assert result["extractor"] == "docx-xml"


def test_unsupported_binary_attachment_has_controlled_error() -> None:
    with pytest.raises(HTTPException) as error:
        extract_uploaded_file(_upload("archive.bin", b"\x00\x01binary"))

    assert error.value.status_code == 422
    assert error.value.detail == "FILE_TEXT_EXTRACTION_UNSUPPORTED"


def test_image_attachment_requires_explicit_vision_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.file_extract._extract_local_image", lambda *_args: None)
    # The test defaults use local-only mode, so no image bytes can leave the process.
    with pytest.raises(HTTPException) as error:
        extract_uploaded_file(_upload("label.png", b"\x89PNG\r\n\x1a\n"))

    assert error.value.status_code == 503
    assert error.value.detail == "FILE_IMAGE_TEXT_EXTRACTION_UNAVAILABLE"
