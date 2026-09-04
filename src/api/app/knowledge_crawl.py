"""Controlled knowledge crawl → staging pipeline (never auto-ingests).

Fetches only allowlisted sources, writes UTF-8 markdown drafts under
``src/runtime/knowledge/staging/``, and records a crawl run ledger. Live RAG
ingest still requires human promotion into ``src/runtime/knowledge/approved/``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_ROOT = REPO_ROOT / "src" / "runtime" / "knowledge"
ALLOWLIST_PATH = KNOWLEDGE_ROOT / "crawl" / "allowlist.json"
FIXTURES_ROOT = KNOWLEDGE_ROOT / "crawl" / "fixtures"
STAGING_ROOT = KNOWLEDGE_ROOT / "staging"
RUNS_PATH = STAGING_ROOT / "crawl_runs.jsonl"

# Source ids double as staging file names; reject anything that could escape
# the staging tree (path traversal) or hide files.
_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

STAGING_DISCLAIMER = (
    "staging 草稿仅供人工审核，不是正式检索证据；"
    "批准晋升并 dry-run 入库后才会参与本地 RAG 检索。"
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False
        if tag in {"p", "div", "li", "h1", "h2", "h3", "br", "tr"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        joined = " ".join(self._chunks)
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", joined)).strip()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def load_allowlist(path: Path | None = None) -> dict[str, Any]:
    target = path or ALLOWLIST_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ValueError("ALLOWLIST_INVALID")
    return payload


def _host_allowed(
    url: str,
    source: dict[str, Any],
    *,
    live: bool,
    allowed_hosts: list[str] | None = None,
) -> None:
    parsed = urlparse(url)
    if url.startswith("fixture://"):
        return
    if parsed.scheme.lower() != "https":
        raise ValueError("HTTPS_ONLY")
    if not live:
        raise ValueError("LIVE_FETCH_DISABLED")
    # Live sources must be explicitly enabled in allowlist.
    if not source.get("enabled", False):
        raise ValueError("SOURCE_DISABLED")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("HOST_MISSING")
    hosts = [h.lower() for h in (allowed_hosts or [])]
    if hosts and host not in hosts and not any(host.endswith(f".{h}") for h in hosts):
        raise ValueError("HOST_NOT_ALLOWLISTED")


def _fixture_overrides_root() -> Path:
    """Runtime overlays produced by the classroom "simulate update" helper.

    Lives under the gitignored staging tree so repository fixtures stay
    pristine while the next crawl still observes changed content.
    """
    return STAGING_ROOT / "fixture_overrides"


def _fixture_override_path(url: str) -> Path | None:
    if not url.startswith("fixture://"):
        return None
    relative = url.removeprefix("fixture://knowledge/")
    path = _fixture_overrides_root() / relative
    return path if path.is_file() else None


def _fetch_bytes(url: str, *, user_agent: str, max_bytes: int, live: bool) -> bytes:
    if url.startswith("fixture://"):
        relative = url.removeprefix("fixture://knowledge/")
        path = _fixture_override_path(url) or (FIXTURES_ROOT / relative)
        if not path.is_file():
            raise FileNotFoundError(f"FIXTURE_NOT_FOUND:{relative}")
        data = path.read_bytes()
        if len(data) > max_bytes:
            raise ValueError("PAGE_TOO_LARGE")
        return data
    if not live:
        raise ValueError("LIVE_FETCH_DISABLED")
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "text/html"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 — allowlisted HTTPS only
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("PAGE_TOO_LARGE")
    return data


def html_to_markdown(title: str, html: str, *, source_url: str, license_name: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    body = parser.text()
    lines = [
        f"# {title}",
        "",
        "> 状态：staging 草稿，未经正式审核，不得直接当作 RAG 正式证据。",
        f"> 来源：{source_url}",
        f"> 许可意图：{license_name}",
        "> 边界：教学/科普摘要用途；不做诊断、处方、剂量建议；禁止导流。",
        "",
        body or "_（未能提取正文，请人工核对原页）_",
        "",
    ]
    return "\n".join(lines)


def _staging_meta_path(source_id: str) -> Path:
    return STAGING_ROOT / "meta" / f"{source_id}.json"


def _staging_doc_path(source_id: str) -> Path:
    return STAGING_ROOT / "documents" / f"{source_id}.md"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def source_is_due(
    source: dict[str, Any],
    meta: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> bool:
    """True when never fetched or past refresh_hours since last fetch."""
    stamp = now or datetime.now(UTC)
    if meta is None:
        return True
    fetched = _parse_iso(str(meta.get("fetched_at") or ""))
    if fetched is None:
        return True
    hours = float(source.get("refresh_hours") or 168)
    age_hours = (stamp - fetched).total_seconds() / 3600.0
    return age_hours >= hours


def crawl_source(
    source: dict[str, Any],
    *,
    policy: dict[str, Any],
    live: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    source_id = str(source["id"])
    url = str(source["url"])
    title = str(source.get("title") or source_id)
    license_name = str(source.get("license") or "unknown")
    max_bytes = int(policy.get("max_bytes_per_page") or 500_000)
    user_agent = str(policy.get("user_agent") or "HomeCareTwinKnowledgeBot/1.0")
    allowed_hosts = list(policy.get("allowed_hosts") or [])
    stamp = now or datetime.now(UTC)

    _host_allowed(url, source, live=live, allowed_hosts=allowed_hosts)
    raw = _fetch_bytes(url, user_agent=user_agent, max_bytes=max_bytes, live=live)
    html = raw.decode("utf-8", errors="replace")
    markdown = html_to_markdown(title, html, source_url=url, license_name=license_name)
    content_hash = _sha256(markdown)

    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    (STAGING_ROOT / "documents").mkdir(parents=True, exist_ok=True)
    (STAGING_ROOT / "meta").mkdir(parents=True, exist_ok=True)

    meta_path = _staging_meta_path(source_id)
    previous = None
    if meta_path.is_file():
        previous = json.loads(meta_path.read_text(encoding="utf-8"))

    first_fetch = previous is None
    unchanged = bool(previous and previous.get("content_sha256") == content_hash)
    doc_path = _staging_doc_path(source_id)
    if not unchanged:
        doc_path.write_text(markdown, encoding="utf-8")

    meta = {
        "source_id": source_id,
        "title": title,
        "url": url,
        "license": license_name,
        "topics": source.get("topics") or [],
        "status": previous.get("status", "draft") if previous and unchanged else "draft",
        "content_sha256": content_hash,
        "document_path": _relpath(doc_path),
        "fetched_at": stamp.isoformat(),
        "unchanged": unchanged,
        "first_fetch": first_fetch,
        # Transparency flag: content came from a classroom "simulate update"
        # overlay, not from the pristine repository fixture.
        "demo_override": _fixture_override_path(url) is not None,
        "review_notes": (previous or {}).get("review_notes", ""),
        "approved_by": (previous or {}).get("approved_by"),
        "approved_at": (previous or {}).get("approved_at"),
    }
    if unchanged and previous:
        # Keep prior review state when content did not change.
        for key in ("status", "review_notes", "approved_by", "approved_at"):
            if key in previous:
                meta[key] = previous[key]
        meta["unchanged"] = True
    else:
        meta["status"] = "draft"
        meta["approved_by"] = None
        meta["approved_at"] = None

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def append_run_ledger(entry: dict[str, Any]) -> None:
    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    with RUNS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _selectable_sources(
    allowlist: dict[str, Any],
    *,
    live: bool,
    source_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for source in allowlist["sources"]:
        if not isinstance(source, dict):
            continue
        if source_ids and source.get("id") not in source_ids:
            continue
        # Fixtures always run; live remote sources need enabled=true and live=true.
        url = str(source.get("url") or "")
        if url.startswith("fixture://") or (live and source.get("enabled", False)):
            selected.append(source)
    return selected


def run_crawl(
    *,
    live: bool = False,
    source_ids: list[str] | None = None,
    due_only: bool = False,
    allowlist_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    allowlist = load_allowlist(allowlist_path)
    policy = allowlist.get("policy") or {}
    stamp = now or datetime.now(UTC)
    selected = _selectable_sources(allowlist, live=live, source_ids=source_ids)
    if due_only:
        meta_by_id = {item["source_id"]: item for item in list_staging()}
        selected = [
            source
            for source in selected
            if source_is_due(source, meta_by_id.get(str(source["id"])), now=stamp)
        ]

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source in selected:
        try:
            results.append(crawl_source(source, policy=policy, live=live, now=stamp))
        except Exception as exc:  # noqa: BLE001 — collect per-source failures
            logger.exception("knowledge crawl failed for %s", source.get("id"))
            errors.append({"source_id": str(source.get("id")), "error": str(exc)})

    report = {
        "ok": not errors,
        "live": live,
        "due_only": due_only,
        "fetched": len(results),
        "unchanged": sum(1 for item in results if item.get("unchanged")),
        "changed": sum(1 for item in results if not item.get("unchanged")),
        "new_sources": sum(1 for item in results if item.get("first_fetch")),
        "errors": errors,
        "results": results,
        "auto_ingest": False,
        "next_step": "人工审核 staging 后执行 promote_knowledge_staging.py",
        "disclaimer": "抓取结果仅为草稿；正式 RAG 仍须批准清单入库。",
    }
    append_run_ledger(
        {
            "ran_at": stamp.isoformat(),
            "live": live,
            "due_only": due_only,
            "fetched": report["fetched"],
            "changed": report["changed"],
            "errors": errors,
        }
    )
    return report


def crawl_ops_status(*, live_preview: bool = False) -> dict[str, Any]:
    """Dashboard status for continuous KB refresh (never triggers network)."""
    allowlist = load_allowlist()
    policy = allowlist.get("policy") or {}
    staging = {item["source_id"]: item for item in list_staging()}
    now = datetime.now(UTC)
    sources = []
    due_ids: list[str] = []
    for source in allowlist.get("sources") or []:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("id") or "")
        meta = staging.get(source_id)
        due = source_is_due(source, meta, now=now)
        if due:
            due_ids.append(source_id)
        url = str(source.get("url") or "")
        sources.append(
            {
                "source_id": source_id,
                "title": source.get("title"),
                "url": url,
                "enabled": bool(source.get("enabled", False)),
                "refresh_hours": source.get("refresh_hours"),
                "topics": source.get("topics") or [],
                "is_fixture": url.startswith("fixture://"),
                "due": due,
                "staging_status": (meta or {}).get("status"),
                "fetched_at": (meta or {}).get("fetched_at"),
                "content_sha256": (meta or {}).get("content_sha256"),
                "unchanged": (meta or {}).get("unchanged"),
                "demo_override": bool((meta or {}).get("demo_override")),
            }
        )
    recent_runs: list[dict[str, Any]] = []
    if RUNS_PATH.is_file():
        lines = RUNS_PATH.read_text(encoding="utf-8").strip().splitlines()
        for line in lines[-5:]:
            try:
                recent_runs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {
        "auto_ingest": False,
        "https_only": bool(policy.get("https_only", True)),
        "requires_human_review": bool(policy.get("requires_human_review", True)),
        "allowed_hosts": list(policy.get("allowed_hosts") or []),
        "source_count": len(sources),
        "due_count": len(due_ids),
        "due_source_ids": due_ids,
        "staging_total": len(staging),
        "sources": sources,
        "recent_runs": recent_runs,
        "live_preview": live_preview,
        "disclaimer": "到期仅表示建议刷新；正式检索仍须批准晋升并独立入库。",
    }


def list_staging() -> list[dict[str, Any]]:
    meta_dir = STAGING_ROOT / "meta"
    if not meta_dir.is_dir():
        return []
    items = []
    for path in sorted(meta_dir.glob("*.json")):
        items.append(json.loads(path.read_text(encoding="utf-8")))
    return items


def _validate_source_id(source_id: str) -> None:
    if not _SOURCE_ID_RE.match(source_id or ""):
        raise FileNotFoundError("STAGING_NOT_FOUND")


def get_staging_detail(source_id: str) -> dict[str, Any]:
    """Read-only staging draft detail: metadata plus the fetched markdown body.

    Staging content is review material only — the response says so explicitly
    so callers cannot mistake a draft for approved retrieval evidence.
    """
    _validate_source_id(source_id)
    meta_path = _staging_meta_path(source_id)
    if not meta_path.is_file():
        raise FileNotFoundError("STAGING_NOT_FOUND")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    doc_path = _staging_doc_path(source_id)
    content_available = doc_path.is_file()
    return {
        **meta,
        "content_markdown": (
            doc_path.read_text(encoding="utf-8") if content_available else ""
        ),
        "content_available": content_available,
        "is_formal_evidence": False,
        "disclaimer": STAGING_DISCLAIMER,
    }


def simulate_fixture_update(
    *,
    actor_id: str,
    source_ids: list[str] | None = None,
    reset: bool = False,
    allowlist_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Teaching-demo only: overlay fixture sources with a clearly marked update.

    Writes runtime overlays under the gitignored staging tree (repository
    fixtures are never modified) so the next crawl detects a content change,
    resets the draft to ``draft`` and requires review again. Fixture-only —
    remote sources are never touched, nothing goes over the network, and
    nothing is auto-ingested.
    """
    stamp = now or datetime.now(UTC)
    overrides = _fixture_overrides_root()

    if reset:
        cleared: list[str] = []
        if overrides.is_dir():
            for path in sorted(overrides.glob("*.html")):
                path.unlink()
                cleared.append(path.name)
        return {
            "ok": True,
            "teaching_demo": True,
            "reset": True,
            "cleared": cleared,
            "auto_ingest": False,
            "next_step": "再次抓取将回到仓库夹具原文（同样会被识别为「有更新」并重置为 draft）。",
            "disclaimer": (
                "模拟更新仅影响本地运行时 overlay，不修改仓库夹具，不触网，永不自动入库。"
            ),
        }

    allowlist = load_allowlist(allowlist_path)
    bumped: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    overrides.mkdir(parents=True, exist_ok=True)
    for source in allowlist.get("sources") or []:
        if not isinstance(source, dict):
            continue
        sid = str(source.get("id") or "")
        url = str(source.get("url") or "")
        if source_ids and sid not in source_ids:
            continue
        if not url.startswith("fixture://"):
            if source_ids:
                skipped.append({"source_id": sid, "reason": "REMOTE_SOURCE_NOT_SIMULATED"})
            continue
        relative = url.removeprefix("fixture://knowledge/")
        original = FIXTURES_ROOT / relative
        if not original.is_file():
            skipped.append({"source_id": sid, "reason": "FIXTURE_NOT_FOUND"})
            continue
        override_path = overrides / relative
        bump = 1
        if override_path.is_file():
            match = re.search(r"demo-bump: (\d+)", override_path.read_text(encoding="utf-8"))
            bump = int(match.group(1)) + 1 if match else 2
        note = (
            f"<section data-demo-update=\"true\"><!-- demo-bump: {bump} -->"
            f"<h2>教学演示模拟更新 v{bump}</h2>"
            f"<p>本段由「模拟来源更新」教学功能于 {stamp.isoformat()} 追加，"
            "用于课堂演示变更检测与重新审核流程；不是真实来源更新，"
            "不构成任何诊断、处方或剂量建议。</p></section>"
        )
        text = original.read_text(encoding="utf-8")
        if "</body>" in text:
            text = text.replace("</body>", f"{note}\n</body>", 1)
        else:
            text = f"{text}\n{note}"
        override_path.write_text(text, encoding="utf-8")
        bumped.append({"source_id": sid, "demo_bump": bump})

    return {
        "ok": True,
        "teaching_demo": True,
        "reset": False,
        "requested_by": actor_id,
        "bumped": bumped,
        "skipped": skipped,
        "auto_ingest": False,
        "next_step": (
            "点击「全量抓取」或「到期刷新」，这些来源会显示「有更新」并重置为 draft 待审。"
        ),
        "disclaimer": (
            "模拟更新仅影响本地运行时 overlay，不修改仓库夹具，不触网，永不自动入库。"
        ),
    }


def mark_staging_reviewed(
    source_id: str,
    *,
    reviewer: str,
    notes: str = "",
    approve: bool = False,
    reject: bool = False,
) -> dict[str, Any]:
    if approve and reject:
        raise ValueError("APPROVE_REJECT_CONFLICT")
    _validate_source_id(source_id)
    path = _staging_meta_path(source_id)
    if not path.is_file():
        raise FileNotFoundError("STAGING_NOT_FOUND")
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["review_notes"] = notes
    if reject:
        meta["status"] = "rejected"
        meta["approved_by"] = None
        meta["approved_at"] = None
        meta["rejected_by"] = reviewer
        meta["rejected_at"] = datetime.now(UTC).isoformat()
    elif approve:
        meta["status"] = "approved"
        meta["approved_by"] = reviewer
        meta["approved_at"] = datetime.now(UTC).isoformat()
        meta.pop("rejected_by", None)
        meta.pop("rejected_at", None)
    else:
        meta["status"] = "reviewed"
        meta["approved_by"] = None
        meta["approved_at"] = None
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def promote_approved_staging(
    *,
    actor_id: str,
    target_root: Path | None = None,
) -> dict[str, Any]:
    """Copy approved staging docs into approved/incoming and build a draft manifest."""
    target = target_root or (REPO_ROOT / "docs" / "knowledge" / "approved" / "incoming")
    target.mkdir(parents=True, exist_ok=True)
    documents = []
    promoted = []
    for meta in list_staging():
        if meta.get("status") != "approved":
            continue
        source_id = meta["source_id"]
        src = Path(meta["document_path"])
        if not src.is_absolute():
            src = REPO_ROOT / meta["document_path"]
        if not src.is_file():
            continue
        text = src.read_text(encoding="utf-8")
        dest_name = f"{source_id}.md"
        dest = target / dest_name
        dest.write_text(text, encoding="utf-8")
        version = f"crawl-{meta['content_sha256'][:12]}"
        rel_path = f"incoming/{dest_name}"
        if target_root is not None:
            # Tests may promote into a temp folder; keep path stable for manifest.
            rel_path = dest_name
        documents.append(
            {
                "path": rel_path,
                "title": meta["title"],
                "source": f"crawl:{source_id}",
                "license": meta.get("license") or "unknown",
                "version": version,
                "permission_scope": {"internal": True},
                "content_sha256": _sha256(text),
            }
        )
        meta["status"] = "promoted"
        meta["promoted_at"] = datetime.now(UTC).isoformat()
        meta["promoted_by"] = actor_id
        _staging_meta_path(source_id).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        promoted.append(source_id)

    manifest = {
        "manifest_version": "1",
        "status": "approved",
        "approval_note": (
            f"由 {actor_id} 从 staging 晋升；仍须独立 index-version 入库。"
            "禁止未审核自动抓取直写正式索引。"
        ),
        "documents": documents,
    }
    manifest_path = target / "正式知识清单.crawl.json"
    if documents:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    manifest_rel = None
    if documents:
        try:
            manifest_rel = str(manifest_path.resolve().relative_to(REPO_ROOT.resolve())).replace(
                "\\", "/"
            )
        except ValueError:
            manifest_rel = str(manifest_path)
    return {
        "ok": True,
        "promoted": promoted,
        "document_count": len(documents),
        "manifest_path": manifest_rel,
        "ingest_hint": (
            "uv run python scripts/ingest_local_knowledge.py "
            "--manifest src/runtime/knowledge/approved/incoming/正式知识清单.crawl.json "
            "--source-root src/runtime/knowledge/approved "
            "--actor-id knowledge-steward "
            "--index-version approved-crawl-v1 --dry-run"
        ),
    }
