"""Refuse-route gold set and match-explanation regressions."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REFUSE_GOLD = REPO_ROOT / "docs" / "demo" / "本地RAG拒答金标集.json"


def test_refuse_gold_routes_away_from_casual_chat() -> None:
    from app.tool_call import classify_question

    cases = json.loads(REFUSE_GOLD.read_text(encoding="utf-8"))["cases"]
    assert cases
    for case in cases:
        query_type = classify_question(case["query"])
        expected = case["expect_query_type"]
        if isinstance(expected, list):
            assert query_type in expected, (case["id"], query_type)
        else:
            assert query_type == expected, (case["id"], query_type)
        for banned in case.get("must_not_query_type") or []:
            assert query_type != banned, (case["id"], query_type)


def test_retrieve_includes_match_reason(db_session) -> None:
    from app.knowledge import add_document, retrieve
    from app.knowledge_synonyms import reload_synonyms

    reload_synonyms()
    add_document(
        db_session,
        title="过期药品回收说明",
        content="过期药品应移出常用区并优先走回收渠道，不指导继续服用。",
        source="match-reason-fixture",
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
    assert hits[0].get("match_reason")
    assert "同义词" in hits[0]["match_reason"] or "关键词" in hits[0]["match_reason"]


def test_synonym_table_json_loads() -> None:
    from app.knowledge_synonyms import expand_query_tokens, reload_synonyms

    reload_synonyms()
    expanded = expand_query_tokens(["expiry"])
    assert any(token.startswith("过期") or token == "expired" for token in expanded)
