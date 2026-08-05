"""Offline tests for the relay review contract and blocking policy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "relay_review_bot.py"
SPEC = importlib.util.spec_from_file_location("relay_review_bot", SCRIPT)
assert SPEC and SPEC.loader
BOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOT)


def review(*, completion: str = "complete", priority: str | None = None) -> dict:
    must_fix = []
    if priority:
        must_fix.append(
            {
                "priority": priority,
                "location": "src/example.py:1",
                "issue": "示例问题",
                "impact": "示例影响",
                "recommendation": "示例建议",
            }
        )
    return {
        "task_completion": completion,
        "summary": "审查结论",
        "acceptance_checks": [
            {
                "status": "complete",
                "criterion": "任务标准",
                "evidence": "tests/unit/test_relay_review_bot.py",
            }
        ],
        "must_fix": must_fix,
        "risks": [],
        "review_conclusion": {
            "needs_human_reviewer": False,
            "recommend_merge": completion == "complete" and not priority,
            "reason": "测试结论",
        },
    }


def test_extract_json_accepts_fenced_model_output() -> None:
    value = BOT.extract_json('说明文字\n```json\n{"task_completion":"complete"}\n```')
    assert value["task_completion"] == "complete"


def test_review_gate_blocks_incomplete_and_p1() -> None:
    assert BOT.review_requires_failure(review(completion="partial"))
    assert BOT.review_requires_failure(review(priority="P1"))


def test_review_gate_allows_complete_without_p0_or_p1() -> None:
    value = review(priority="P2")
    BOT.validate_review(value)
    assert not BOT.review_requires_failure(value)


def test_secret_guard_rejects_private_key_and_api_key_patterns() -> None:
    assert BOT.likely_secret("-----BEGIN PRIVATE KEY-----")
    assert BOT.likely_secret('api_key = "12345678901234567890"')
    assert not BOT.likely_secret("REVIEW_API_KEY = ${{ secrets.REVIEW_API_KEY }}")
