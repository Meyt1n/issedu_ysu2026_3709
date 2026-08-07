"""Tests for the non-blocking Relay service outage policy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "relay_review_bot.py"
SPEC = importlib.util.spec_from_file_location("relay_review_bot", SCRIPT)
assert SPEC and SPEC.loader
BOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOT)


@pytest.mark.parametrize(
    "error",
    [
        BOT.RelayUnavailableError("中转 API 调用失败（TimeoutError）。"),
        BOT.RelayUnavailableError("中转 API 未返回符合要求的 JSON 审查结果。"),
        BOT.RelayUnavailableError("中转 API 调用失败（HTTP 503）。"),
    ],
)
def test_relay_service_outage_is_advisory(error: Exception) -> None:
    assert BOT.relay_service_unavailable(error)
    comment = BOT.unavailable_comment(str(error))
    assert "不阻塞其它 Required Checks" in comment


def test_configuration_or_local_failures_remain_blocking() -> None:
    assert not BOT.relay_service_unavailable(
        BOT.BotError("未配置 REVIEW_API_URL、REVIEW_API_KEY 或 REVIEW_MODEL。")
    )
    assert not BOT.relay_service_unavailable(
        BOT.BotError("REVIEW_API_WIRE 只能是 responses 或 chat_completions。")
    )
    assert not BOT.relay_service_unavailable(
        BOT.BotError("中转 API 调用失败（HTTP 401）。")
    )
    assert not BOT.relay_service_unavailable(
        BOT.BotError("PR 正文或 diff 命中疑似密钥模式")
    )
    assert not BOT.relay_service_unavailable(
        BOT.BotError("GitHub API 请求失败（HTTP 403）。")
    )


def _configure_main_test(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> list[str]:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        '{"pull_request":{"number":24},"repository":{"full_name":"Meyt1n/issedu_ysu2026_3709"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("REVIEW_API_URL", "https://relay.test/v1/responses")
    monkeypatch.setenv("REVIEW_API_KEY", "test-key")
    monkeypatch.setenv("REVIEW_MODEL", "test-model")
    monkeypatch.setattr(
        BOT,
        "build_context",
        lambda event: (
            "Meyt1n/issedu_ysu2026_3709",
            "24",
            "abc123",
            24,
            "system prompt\n\nuser prompt",
        ),
    )
    comments: list[str] = []
    monkeypatch.setattr(BOT, "upsert_comment", lambda repo, number, body: comments.append(body))
    return comments


def test_main_returns_success_when_relay_api_times_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comments = _configure_main_test(monkeypatch, tmp_path)
    monkeypatch.setattr(
        BOT,
        "relay_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            BOT.RelayUnavailableError("中转 API 调用失败（TimeoutError）。")
        ),
    )

    assert BOT.main() == 0
    assert comments and "不阻塞其它 Required Checks" in comments[0]


def test_main_returns_success_when_model_returns_invalid_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    comments = _configure_main_test(monkeypatch, tmp_path)
    monkeypatch.setattr(BOT, "relay_request", lambda *args, **kwargs: {})
    monkeypatch.setattr(BOT, "extract_response_text", lambda response: "not-json")

    assert BOT.main() == 0
    assert comments and "不阻塞其它 Required Checks" in comments[0]
