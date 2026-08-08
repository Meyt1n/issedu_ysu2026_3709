"""Build a metadata-only inventory for a public Mendeley Data version.

The inventory deliberately excludes signed download/view URLs and media bytes.
It is intended to reconcile a landing-page description with the files exposed
by the public API before any controlled-domain download or annotation work.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_DATASET_ID = "bsmy5jjysy"
DEFAULT_VERSION = 3
DEFAULT_DESCRIPTION_COUNT = 2000


def _content_details(record: dict[str, Any]) -> dict[str, Any]:
    details = record.get("content_details")
    return details if isinstance(details, dict) else {}


def normalize_file(record: dict[str, Any]) -> dict[str, Any]:
    """Keep only stable metadata needed for a reproducible inventory."""

    details = _content_details(record)
    return {
        "filename": str(record.get("filename", "")),
        "id": str(record.get("id", "")),
        "content_type": str(details.get("content_type", "")),
        "size": int(record.get("size", details.get("size", 0)) or 0),
        "sha256": str(details.get("sha256_hash", "")).lower(),
        "status": str(record.get("status", "")),
    }


def summarize_inventory(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize and validate stable file metadata without reading media."""

    normalized = [normalize_file(record) for record in files]
    filenames = [item["filename"] for item in normalized]
    hashes = [item["sha256"] for item in normalized]
    invalid_hashes = sorted(
        {
            digest
            for digest in hashes
            if not HEX_SHA256.fullmatch(digest)
        }
    )
    duplicate_hashes = sorted(
        digest
        for digest, count in Counter(hashes).items()
        if digest and count > 1
    )
    duplicate_filenames = sorted(
        filename
        for filename, count in Counter(filenames).items()
        if filename and count > 1
    )
    return {
        "file_count": len(normalized),
        "total_bytes": sum(item["size"] for item in normalized),
        "content_types": dict(sorted(Counter(item["content_type"] for item in normalized).items())),
        "extensions": dict(
            sorted(
                Counter(Path(item["filename"]).suffix.lower() for item in normalized).items()
            )
        ),
        "statuses": dict(sorted(Counter(item["status"] for item in normalized).items())),
        "invalid_sha256_count": len(invalid_hashes),
        "duplicate_sha256_count": len(duplicate_hashes),
        "duplicate_filename_count": len(duplicate_filenames),
        "invalid_sha256": invalid_hashes,
        "duplicate_sha256": duplicate_hashes,
        "duplicate_filenames": duplicate_filenames,
    }


def build_report(
    *,
    dataset_id: str,
    version: int,
    files: list[dict[str, Any]],
    page_description_count: int,
    retrieved_at: str,
) -> dict[str, Any]:
    """Create a stable, URL-free report suitable for repository evidence."""

    normalized = [normalize_file(record) for record in files]
    summary = summarize_inventory(files)
    return {
        "source": {
            "dataset_id": dataset_id,
            "version": version,
            "doi": f"10.17632/{dataset_id}.{version}",
            "page_url": f"https://data.mendeley.com/datasets/{dataset_id}/{version}",
            "files_api_url": (
                "https://data.mendeley.com/public-api/datasets/"
                f"{dataset_id}/files?folder_id=root&version={version}"
            ),
            "retrieved_at": retrieved_at,
        },
        "page_description_count": page_description_count,
        "api_inventory": summary,
        "reconciliation": {
            "count_matches_description": summary["file_count"] == page_description_count,
            "decision": (
                "BLOCKED_COUNT_MISMATCH"
                if summary["file_count"] != page_description_count
                else "REQUIRES_LICENSE_PRIVACY_AND_SPLIT_REVIEW"
            ),
        },
        "evidence_note": (
            "Metadata only: media bytes and signed download/view URLs are excluded. "
            "Run this script again before any controlled-domain download."
        ),
        "files": normalized,
    }


def fetch_files(dataset_id: str, version: int) -> list[dict[str, Any]]:
    url = (
        "https://data.mendeley.com/public-api/datasets/"
        f"{dataset_id}/files?folder_id=root&version={version}"
    )
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.mendeley-public-dataset.1+json",
            "User-Agent": "HomeCare-Twin-HCT-201-metadata-audit/1.0",
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS endpoint above
        payload = json.load(response)
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("Mendeley public API did not return a file list")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    parser.add_argument("--version", type=int, default=DEFAULT_VERSION)
    parser.add_argument("--page-description-count", type=int, default=DEFAULT_DESCRIPTION_COUNT)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    files = fetch_files(args.dataset_id, args.version)
    report = build_report(
        dataset_id=args.dataset_id,
        version=args.version,
        files=files,
        page_description_count=args.page_description_count,
        retrieved_at=datetime.now(UTC).isoformat(),
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    summary = {
        key: report[key]
        for key in ("source", "page_description_count", "api_inventory", "reconciliation")
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
