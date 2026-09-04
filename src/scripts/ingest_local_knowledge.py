"""Ingest an approved local knowledge manifest into the HCT-401 store.

The command deliberately accepts a manifest instead of scanning a directory.
That keeps source, licence, version, permission scope and content hash
explicit and makes a local rebuild auditable and repeatable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class IngestError(ValueError):
    """A safe, actionable validation or idempotency error."""


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require_text(value: Any, field: str, *, max_length: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestError(f"MANIFEST_INVALID:{field}")
    result = value.strip()
    if max_length is not None and len(result) > max_length:
        raise IngestError(f"MANIFEST_INVALID:{field}_TOO_LONG")
    return result


def _parse_datetime(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IngestError(f"MANIFEST_INVALID:{field}")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IngestError(f"MANIFEST_INVALID:{field}") from exc


def _datetime_signature(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat()


def _validate_permission_scope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IngestError("MANIFEST_INVALID:permission_scope")
    allowed = {"created_by", "household_ids", "member_ids", "internal"}
    unknown = set(value) - allowed
    if unknown:
        raise IngestError("MANIFEST_INVALID:permission_scope_key")
    if "created_by" in value:
        _require_text(value["created_by"], "permission_scope.created_by", max_length=120)
    for key in ("household_ids", "member_ids"):
        if key in value:
            ids = value[key]
            if not isinstance(ids, list) or any(
                not isinstance(item, str) or not item.strip() for item in ids
            ):
                raise IngestError(f"MANIFEST_INVALID:permission_scope.{key}")
    if "internal" in value and not isinstance(value["internal"], bool):
        raise IngestError("MANIFEST_INVALID:permission_scope.internal")
    return value


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestError("MANIFEST_UNREADABLE") from exc
    if not isinstance(manifest, dict):
        raise IngestError("MANIFEST_INVALID:root")
    if manifest.get("status") != "approved":
        raise IngestError("MANIFEST_NOT_APPROVED")
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise IngestError("MANIFEST_INVALID:documents")
    return manifest


def _resolve_source_path(source_root: Path, relative_path: Any) -> Path:
    path = _require_text(relative_path, "path", max_length=240)
    candidate = Path(path)
    if candidate.is_absolute():
        raise IngestError("PATH_OUTSIDE_SOURCE_ROOT")
    resolved_root = source_root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise IngestError("PATH_OUTSIDE_SOURCE_ROOT") from exc
    if resolved.suffix.lower() not in {".md", ".txt"}:
        raise IngestError("UNSUPPORTED_KNOWLEDGE_FILE")
    if not resolved.is_file():
        raise IngestError("KNOWLEDGE_FILE_NOT_FOUND")
    return resolved


def _validate_document_entry(
    entry: Any,
    *,
    source_root: Path,
) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise IngestError("MANIFEST_INVALID:document_entry")
    path = _resolve_source_path(source_root, entry.get("path"))
    title = _require_text(entry.get("title"), "title", max_length=200)
    source = _require_text(entry.get("source"), "source", max_length=120)
    license_name = _require_text(entry.get("license"), "license", max_length=60)
    if license_name.casefold() in {"unknown", "unverified", ""}:
        raise IngestError("LICENSE_NOT_VERIFIED")
    version = _require_text(entry.get("version"), "version", max_length=40)
    permission_scope = _validate_permission_scope(entry.get("permission_scope"))
    effective_from = _parse_datetime(entry.get("effective_from"), "effective_from")
    effective_until = _parse_datetime(entry.get("effective_until"), "effective_until")
    if effective_from and effective_until and effective_until <= effective_from:
        raise IngestError("MANIFEST_INVALID:EFFECTIVE_WINDOW")
    expected_hash = _require_text(entry.get("content_sha256"), "content_sha256")
    valid_hash = len(expected_hash) == 64 and all(
        char in "0123456789abcdefABCDEF" for char in expected_hash
    )
    if not valid_hash:
        raise IngestError("MANIFEST_INVALID:content_sha256")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise IngestError("KNOWLEDGE_FILE_EMPTY")
    if _sha256(content) != expected_hash.casefold():
        raise IngestError(f"CONTENT_HASH_MISMATCH:{path.name}")
    return {
        "path": str(path),
        "title": title,
        "source": source,
        "license": license_name,
        "version": version,
        "permission_scope": permission_scope,
        "content": content,
        "content_hash": expected_hash.casefold(),
        "effective_from": effective_from,
        "effective_until": effective_until,
    }


def _document_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item["title"],
        item["source"],
        item["license"],
        item["version"],
        item["content_hash"],
        _canonical(item["permission_scope"]),
        _datetime_signature(item["effective_from"]),
        _datetime_signature(item["effective_until"]),
    )


def ingest_manifest(
    session,
    *,
    manifest_path: Path,
    source_root: Path | None,
    actor_id: str,
    index_version: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate and atomically ingest a manifest into an existing session."""
    from sqlalchemy import select

    from app.knowledge import (
        KnowledgeDocument,
        KnowledgeIndex,
        add_document,
        compute_index_checksum,
        create_index_snapshot,
        normalize_permission_scope,
    )

    manifest_path = manifest_path.resolve()
    manifest = load_manifest(manifest_path)
    root = (source_root or manifest_path.parent).resolve()
    actor = _require_text(actor_id, "actor_id", max_length=120)
    version = _require_text(index_version, "index_version", max_length=40)
    items = [_validate_document_entry(entry, source_root=root) for entry in manifest["documents"]]

    actions: list[dict[str, Any]] = []
    creates: list[dict[str, Any]] = []
    for item in items:
        existing = session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.status == "active",
                KnowledgeDocument.title == item["title"],
                KnowledgeDocument.source == item["source"],
                KnowledgeDocument.version == item["version"],
            )
        )
        if existing is None:
            creates.append(item)
            actions.append({"action": "create", "title": item["title"]})
            continue
        # ``add_document`` stamps the ingesting actor into empty scopes so they
        # never become world-readable; replaying the same manifest must compare
        # against the same normalized form or idempotent re-runs would raise a
        # false DOCUMENT_VERSION_CONFLICT.
        normalized_item = {
            **item,
            "permission_scope": normalize_permission_scope(
                item["permission_scope"], created_by=actor
            ),
        }
        if _document_signature(normalized_item) != _document_signature(
            {
                "title": existing.title,
                "source": existing.source,
                "license": existing.license,
                "version": existing.version,
                "content_hash": existing.content_hash,
                "permission_scope": existing.permission_scope or {},
                "effective_from": existing.effective_from,
                "effective_until": existing.effective_until,
            }
        ):
            raise IngestError(f"DOCUMENT_VERSION_CONFLICT:{item['title']}")
        actions.append({"action": "skip", "title": item["title"], "document_id": existing.id})

    existing_index = session.scalar(
        select(KnowledgeIndex).where(KnowledgeIndex.version == version)
    )
    if existing_index is not None and creates:
        raise IngestError(f"INDEX_VERSION_CONFLICT:{version}")

    try:
        created: list[dict[str, Any]] = []
        if not dry_run:
            for item in creates:
                doc = add_document(
                    session,
                    title=item["title"],
                    content=item["content"],
                    source=item["source"],
                    created_by=actor,
                    license=item["license"],
                    version=item["version"],
                    permission_scope=item["permission_scope"],
                    effective_from=item["effective_from"],
                    effective_until=item["effective_until"],
                )
                created.append({"title": doc.title, "document_id": doc.id})
            session.flush()
            checksum = compute_index_checksum(session)
            if existing_index is None:
                index = create_index_snapshot(
                    session,
                    version=version,
                    created_by=actor,
                )
            elif existing_index.checksum != checksum:
                raise IngestError(f"INDEX_CHECKSUM_CONFLICT:{version}")
            else:
                index = existing_index
            session.commit()
        else:
            created = [{"title": item["title"]} for item in creates]
            checksum = compute_index_checksum(session)
            index = existing_index
            session.rollback()
    except Exception:
        session.rollback()
        raise

    return {
        "manifest": str(manifest_path),
        "source_root": str(root),
        "actor_id": actor,
        "index_version": version,
        "dry_run": dry_run,
        "actions": actions,
        "created": created,
        "index": (
            {
                "index_id": index.id,
                "version": index.version,
                "document_count": index.document_count,
                "chunk_count": index.chunk_count,
                "checksum": index.checksum,
            }
            if index is not None
            else {"version": version, "checksum": checksum, "status": "would_create"}
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--index-version", required=True)
    parser.add_argument(
        "--database-url",
        help="Optional override; do not print credentials in logs",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src" / "api"))
    try:
        from app.db import SessionLocal

        with SessionLocal() as session:
            result = ingest_manifest(
                session,
                manifest_path=args.manifest,
                source_root=args.source_root,
                actor_id=args.actor_id,
                index_version=args.index_version,
                dry_run=args.dry_run,
            )
    except (IngestError, OSError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
