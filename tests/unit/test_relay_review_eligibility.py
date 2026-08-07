"""Tests for the no-Issue Relay Review Bot allowlist."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "scripts"
    / "relay_review_eligibility.py"
)
SPEC = importlib.util.spec_from_file_location("relay_review_eligibility", SCRIPT)
assert SPEC and SPEC.loader
ELIGIBILITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ELIGIBILITY)


def test_bound_issue_requires_review() -> None:
    assert ELIGIBILITY.has_bound_issue("- Issue：Closes #20")


def test_missing_issue_skips_review() -> None:
    assert not ELIGIBILITY.has_bound_issue("添加 2026 年 8 月 7 日早会记录")


def test_related_issue_does_not_opt_in() -> None:
    assert not ELIGIBILITY.has_bound_issue("- Issue：Related to #20")


def test_example_closing_reference_outside_issue_field_does_not_opt_in() -> None:
    body = """## 验收标准\n\nGiven 文档已更新，Then Closes #20 只作为示例。"""
    assert not ELIGIBILITY.has_bound_issue(body)
