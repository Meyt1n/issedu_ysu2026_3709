from __future__ import annotations

from hct201_mendeley_inventory import build_report, summarize_inventory


def _file(name: str, digest: str, *, size: int = 10) -> dict[str, object]:
    return {
        "filename": name,
        "id": f"id-{name}",
        "size": size,
        "status": "COMPLETED",
        "content_details": {
            "content_type": "image/jpeg",
            "size": size,
            "sha256_hash": digest,
            "download_url": "https://signed.example.invalid/should-not-be-recorded",
        },
    }


def test_summary_detects_duplicate_and_invalid_metadata() -> None:
    report = summarize_inventory(
        [
            _file("a.jpg", "a" * 64, size=10),
            _file("b.jpg", "a" * 64, size=20),
            _file("c.jpg", "not-a-sha256"),
        ]
    )

    assert report["file_count"] == 3
    assert report["total_bytes"] == 40
    assert report["duplicate_sha256_count"] == 1
    assert report["invalid_sha256_count"] == 1
    assert report["content_types"] == {"image/jpeg": 3}


def test_report_excludes_signed_urls_and_flags_page_mismatch() -> None:
    report = build_report(
        dataset_id="bsmy5jjysy",
        version=3,
        files=[_file("a.jpg", "a" * 64)],
        page_description_count=2000,
        retrieved_at="2026-08-08T03:00:00+00:00",
    )

    assert report["reconciliation"]["decision"] == "BLOCKED_COUNT_MISMATCH"
    assert report["files"][0] == {
        "filename": "a.jpg",
        "id": "id-a.jpg",
        "content_type": "image/jpeg",
        "size": 10,
        "sha256": "a" * 64,
        "status": "COMPLETED",
    }
