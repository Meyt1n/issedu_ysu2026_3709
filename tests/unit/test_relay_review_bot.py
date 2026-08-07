"""Offline tests for the relay review contract and blocking policy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "relay_review_bot.py"
SPEC = importlib.util.spec_from_file_location("relay_review_bot", SCRIPT)
assert SPEC and SPEC.loader
BOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOT)


def finding(priority: str) -> dict:
    return {
        "priority": priority,
        "location": "src/example.py:1",
        "issue": "示例问题",
        "impact": "示例影响",
        "recommendation": "示例建议",
    }


def risk(priority: str) -> dict:
    return {
        "priority": priority,
        "area": "quality",
        "description": "示例风险",
        "mitigation": "示例缓解措施",
    }


def review(
    *,
    completion: str = "complete",
    priorities: tuple[str, ...] = (),
    risk_priorities: tuple[str, ...] = (),
) -> dict:
    blocking_priorities = {"P0", "P1"}
    has_blocking_finding = any(
        priority in blocking_priorities
        for priority in (*priorities, *risk_priorities)
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
        "must_fix": [finding(priority) for priority in priorities],
        "risks": [risk(priority) for priority in risk_priorities],
        "review_conclusion": {
            "needs_human_reviewer": False,
            "recommend_merge": completion == "complete" and not has_blocking_finding,
            "reason": "测试结论",
        },
    }


def test_extract_json_accepts_fenced_model_output() -> None:
    value = BOT.extract_json('说明文字\n```json\n{"task_completion":"complete"}\n```')
    assert value["task_completion"] == "complete"


def test_review_gate_blocks_incomplete_and_p1() -> None:
    assert BOT.review_requires_failure(review(completion="partial"))
    assert BOT.review_requires_failure(review(priorities=("P1",)))


@pytest.mark.parametrize(
    ("priorities", "risk_priorities"),
    [
        (("P2",), ()),
        ((), ("P2",)),
        (("P2",), ("P2", "P2")),
    ],
)
def test_complete_with_only_p2_findings_passes(
    priorities: tuple[str, ...], risk_priorities: tuple[str, ...]
) -> None:
    value = review(priorities=priorities, risk_priorities=risk_priorities)
    BOT.validate_review(value)
    assert value["review_conclusion"]["recommend_merge"]
    assert not BOT.review_requires_failure(value)


def test_complete_with_p2_and_p1_still_blocks() -> None:
    value = review(priorities=("P2", "P1"), risk_priorities=("P2",))
    BOT.validate_review(value)
    assert not value["review_conclusion"]["recommend_merge"]
    assert BOT.review_requires_failure(value)


def test_secret_guard_rejects_private_key_and_api_key_patterns() -> None:
    assert BOT.likely_secret("-----BEGIN PRIVATE KEY-----")
    assert BOT.likely_secret('api_key = "12345678901234567890"')
    assert not BOT.likely_secret("REVIEW_API_KEY = ${{ secrets.REVIEW_API_KEY }}")
