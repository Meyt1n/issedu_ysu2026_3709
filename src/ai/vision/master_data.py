"""Versioned, offline-only master-data snapshot loading for HCT-205."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .evidence_pipeline import LocalMasterData, MasterDataRecord

SNAPSHOT_SCHEMA = "hct-master-data/v1"
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _unavailable(version: str) -> LocalMasterData:
    return LocalMasterData(version=version, available=False, records=[])


def _canonical_payload(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def load_master_data_snapshot(
    version: str,
    *,
    root: Path,
    approved_versions: set[str] | frozenset[str] = frozenset(),
) -> LocalMasterData:
    """Load a checked local snapshot; never access the network.

    A snapshot is valid only when its filename, declared version, schema,
    record structure and SHA-256 over the payload without ``sha256`` agree.
    Missing, invalid or path-like versions are represented as unavailable so
    callers can safely return UNKNOWN/REVIEW.
    """
    if (
        not _VERSION_PATTERN.fullmatch(version)
        or version == "unavailable"
        or version not in approved_versions
    ):
        return _unavailable(version)
    snapshot_root = root.resolve()
    snapshot_path = (snapshot_root / f"{version}.json").resolve()
    if not snapshot_path.is_relative_to(snapshot_root) or not snapshot_path.is_file():
        return _unavailable(version)
    try:
        document = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            return _unavailable(version)
        declared_hash = document.pop("sha256", None)
        if (
            document.get("schema_version") != SNAPSHOT_SCHEMA
            or document.get("version") != version
            or document.get("approval_status") != "APPROVED"
            or not isinstance(document.get("approval_ref"), str)
            or not document["approval_ref"]
            or document.get("revocation_status") != "ACTIVE"
            or not isinstance(declared_hash, str)
            or hashlib.sha256(_canonical_payload(document)).hexdigest() != declared_hash
        ):
            return _unavailable(version)
        raw_records = document.get("records")
        if not isinstance(raw_records, list):
            return _unavailable(version)
        records = [MasterDataRecord.model_validate(record) for record in raw_records]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _unavailable(version)
    return LocalMasterData(version=version, available=True, records=records)
