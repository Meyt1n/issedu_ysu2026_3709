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
    needs_human_reviewer: bool = False,
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
            "needs_human_reviewer": needs_human_reviewer,
            "recommend_merge": completion == "complete" and not has_blocking_finding,
            "reason": "测试结论",
        },
    }


def test_extract_json_accepts_fenced_model_output() -> None:
    value = BOT.extract_json('说明文字\n```json\n{"task_completion":"complete"}\n```')
    assert value["task_completion"] == "complete"


def test_complete_task_with_pending_human_review_still_passes_task_gate() -> None:
    value = review(needs_human_reviewer=True)
    BOT.validate_review(value)
    assert not BOT.review_requires_failure(value)
    assert not value["review_conclusion"]["needs_human_reviewer"]
    assert value["review_conclusion"]["recommend_merge"]
    rendered = BOT.render_review(value, "0123456789abcdef")
    assert "merge 即代表完成人工复核" in rendered


def test_review_gate_blocks_incomplete_but_not_risk_findings() -> None:
    assert BOT.review_requires_failure(review(completion="partial"))
    value = review(priorities=("P1",), risk_priorities=("P0",))
    BOT.validate_review(value)
    assert not BOT.review_requires_failure(value)
    rendered = BOT.render_review(value, "0123456789abcdef")
    assert "[P1]" in rendered
    assert "[P0/quality]" in rendered


def test_incomplete_task_still_blocks_with_only_p2_findings() -> None:
    value = review(completion="incomplete", priorities=("P2",), risk_priorities=("P2",))
    BOT.validate_review(value)
    assert BOT.review_requires_failure(value)


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


def test_complete_with_p2_and_p1_is_advisory() -> None:
    value = review(priorities=("P2", "P1"), risk_priorities=("P2",))
    BOT.validate_review(value)
    assert value["review_conclusion"]["recommend_merge"]
    assert not BOT.review_requires_failure(value)


def test_secret_guard_rejects_private_key_and_api_key_patterns() -> None:
    assert BOT.likely_secret("-----BEGIN PRIVATE KEY-----")
    assert BOT.likely_secret('api_key = "12345678901234567890"')
    assert not BOT.likely_secret("REVIEW_API_KEY = ${{ secrets.REVIEW_API_KEY }}")


@pytest.mark.parametrize(
    "message",
    [
        "中转 API 调用失败（TimeoutError）。",
        "中转 API 未返回符合要求的 JSON 审查结果。",
        "未配置 REVIEW_API_URL、REVIEW_API_KEY 或 REVIEW_MODEL。",
    ],
)
def test_relay_service_outage_is_advisory(message: str) -> None:
    assert BOT.relay_service_unavailable(message)
    comment = BOT.unavailable_comment(message)
    assert "不阻塞其它 Required Checks" in comment


def test_local_safety_or_github_failures_remain_blocking() -> None:
    assert not BOT.relay_service_unavailable("PR 正文或 diff 命中疑似密钥模式")
    assert not BOT.relay_service_unavailable("GitHub API 请求失败（HTTP 403）。")


def test_main_returns_success_when_relay_api_times_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        '{"pull_request":{"number":24},"repository":{"full_name":"Meyt1n/issedu_ysu2026_3709"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        BOT,
        "build_context",
        lambda event: ("Meyt1n/issedu_ysu2026_3709", "24", "abc123", 24, "prompt"),
    )
    monkeypatch.setattr(
        BOT,
        "relay_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            BOT.BotError("中转 API 调用失败（TimeoutError）。")
        ),
    )
    comments: list[str] = []
    monkeypatch.setattr(BOT, "upsert_comment", lambda repo, number, body: comments.append(body))

    assert BOT.main() == 0
    assert comments and "不阻塞其它 Required Checks" in comments[0]
