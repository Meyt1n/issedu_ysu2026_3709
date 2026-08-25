"""Gold-set retrieval regression for the demo knowledge base.

Pins natural-language queries to expected teaching documents so expanding
the corpus cannot silently cross-hit unrelated cards.  Synonym cases also
lock the local alias table / light-vector blend.
"""
from __future__ import annotations

import json
from pathlib import Path

from ingest_local_knowledge import ingest_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "docs" / "demo" / "本地RAG知识清单.json"
GOLD_PATH = REPO_ROOT / "docs" / "demo" / "本地RAG检索金标集.json"
APPROVED_EXAMPLE = (
    REPO_ROOT / "docs" / "knowledge" / "approved" / "正式知识清单.example.json"
)


def test_gold_set_top_hit_and_anti_cross(db_session) -> None:
    from app.knowledge import retrieve

    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    assert gold["cases"], "gold set must not be empty"

    result = ingest_manifest(
        db_session,
        manifest_path=MANIFEST_PATH,
        source_root=MANIFEST_PATH.parent,
        actor_id="demo-admin",
        index_version=gold["index_version"],
    )
    assert result["index"]["document_count"] == 23

    for case in gold["cases"]:
        hits = retrieve(
            db_session,
            query=case["query"],
            actor_id="demo-admin",
            top_k=3,
        )
        assert hits, f"{case['id']} returned no hits for {case['query']!r}"
        top_title = hits[0]["title"]
        assert case["expect_title_contains"] in top_title, (
            f"{case['id']}: expected {case['expect_title_contains']!r} in "
            f"top title {top_title!r}"
        )
        for banned in case.get("must_not_title_contains") or []:
            assert banned not in top_title, (
                f"{case['id']}: top title {top_title!r} unexpectedly contains "
                f"banned fragment {banned!r}"
            )


def test_synonym_expansion_helps_english_alias(db_session) -> None:
    from app.knowledge import add_document, retrieve
    from app.knowledge_synonyms import expand_query_tokens

    expanded = expand_query_tokens(["expiry"])
    assert "过期" in expanded or "过期药" in expanded or "expired" in expanded

    add_document(
        db_session,
        title="过期药品回收教学片段",
        content="过期药品应移出常用区并优先走回收渠道，不指导继续服用。",
        source="synonym-fixture",
        created_by="demo-admin",
        version="1",
    )
    db_session.commit()

    hits = retrieve(
        db_session,
        query="expiry medicine take-back",
        actor_id="demo-admin",
        top_k=3,
    )
    assert hits
    assert "过期" in hits[0]["title"] or "过期" in hits[0]["text"]


def test_approved_example_manifest_dry_run_shape() -> None:
    """Formal knowledge lives under docs/knowledge/approved, not docs/demo."""
    payload = json.loads(APPROVED_EXAMPLE.read_text(encoding="utf-8"))
    assert payload["status"] == "approved"
    assert payload["documents"]
    sample = payload["documents"][0]
    assert sample["path"].startswith("samples/")
    sample_path = (
        REPO_ROOT / "docs" / "knowledge" / "approved" / sample["path"]
    )
    assert sample_path.is_file()
    content = sample_path.read_text(encoding="utf-8")
    import hashlib

    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == sample[
        "content_sha256"
    ]
    assert "剂量" in content or "几片" in content
    assert "docs/demo" in content or "禁止" in content
