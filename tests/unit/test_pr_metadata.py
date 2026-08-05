"""Tests for the deterministic PR metadata contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "validate_pr_metadata.py"
SPEC = importlib.util.spec_from_file_location("validate_pr_metadata", SCRIPT)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


WORKFLOW_MARKER = (
    "已阅读[开发前必读与 Vibe Coding 工作流](../docs/vibe-coding/"
    "开发前必读与Vibe%20Coding工作流.md)和[PR 任务关联与 Relay Review Bot "
    "工作流](../docs/vibe-coding/PR任务关联与Relay%20Review%20Bot%20工作流.md)"
)
RECOGNITION_MARKER = (
    "已确认：未确认的视觉识别结果不会进入正式健康状态、风险计算或药物计划；"
    "只有多证据匹配且人工确认后才可入库"
)

VALID_BODY = f"""## 关联任务

- Issue：Closes #11
- Story：HCT-101
- FR/NFR：NFR-04、NFR-06
- 负责人：Meyt1n
- 复核人：Reviewer A

## 变更范围与非目标

- 变更范围：完善 PR 任务和风险门禁。
- 明确不做：不修改业务代码，不上传健康数据。

## 验收与证据

### 验收标准

Given PR 内容完整，When 门禁运行，Then 检查通过并记录 Issue、Story 与证据。

### 测试证据

`uv run pytest`：5 passed；`git diff --check`：通过。

### 人工验收/演示证据

Reviewer A 检查模板、校验脚本和工作流配置。

### 部署、迁移和回滚

不涉及部署和迁移；回滚对应本 PR 提交。

## 安全与隐私门禁

- [x] {WORKFLOW_MARKER}
- [x] 未提交真实健康数据、药品图片、密钥、模型权重、缓存或运行日志
- [x] 已说明权限、撤权、审计、数据删除和网络出口影响
- [x] 已说明 AI 使用、人工复核、证据来源和已知限制
- [x] 没有诊断、处方、停药、换药、买药、问诊、广告或佣金导流
- [x] {RECOGNITION_MARKER}
- [x] 高风险变更已指定第二位人工复核人，或已明确说明不适用

## 合并前同步

- [x] 需求追踪矩阵已更新，或已说明本 PR 不改变需求状态
- [x] 相关 API、OpenAPI、迁移、测试和文档已同步，或已说明不适用
- [x] Relay Review Bot 已完成，或已说明未配置中转服务及替代复核方式
"""


def event(body: str) -> dict:
    return {
        "repository": {"full_name": "Meyt1n/issedu_ysu2026_3709"},
        "pull_request": {"body": body, "number": 12},
    }


def test_meaningful_rejects_placeholder_and_pass_only_values() -> None:
    for value in ("TODO: run tests", "待项目组指定", "通过", "passed", "不适用"):
        assert not VALIDATOR.meaningful(value)


def test_meaningful_allows_pending_confirmation_as_business_state() -> None:
    assert VALIDATOR.meaningful("Reviewer A 检查待确认风险卡状态。")


def test_issue_reference_must_be_in_issue_field(monkeypatch) -> None:
    monkeypatch.setattr(VALIDATOR, "github_issue_exists", lambda *_args: (True, ""))
    body = VALID_BODY.replace("- Issue：Closes #11", "- Issue：Closes #")
    body = body.replace("Given PR 内容完整", "Given Closes #11 只出现在验收示例中")
    errors = VALIDATOR.validate_event(event(body))
    assert any("一个且仅一个 Closes" in error for error in errors)


def test_unknown_requirement_id_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(VALIDATOR, "github_issue_exists", lambda *_args: (True, ""))
    body = VALID_BODY.replace("NFR-04、NFR-06", "NFR-999")
    errors = VALIDATOR.validate_event(event(body))
    assert any("NFR-999" in error for error in errors)


def test_high_risk_scope_requires_distinct_reviewer(monkeypatch) -> None:
    monkeypatch.setattr(VALIDATOR, "github_issue_exists", lambda *_args: (True, ""))
    body = VALID_BODY.replace(
        "变更范围：完善 PR 任务和风险门禁。", "变更范围：修改成员授权和撤权规则。"
    )
    body = body.replace("复核人：Reviewer A", "复核人：Meyt1n")
    body = body.replace("- 负责人：Meyt1n", "- 负责人：Meyt1n")
    errors = VALIDATOR.validate_event(event(body))
    assert any("自我复核" in error for error in errors)


def test_valid_event_satisfies_contract(monkeypatch) -> None:
    monkeypatch.setattr(VALIDATOR, "github_issue_exists", lambda *_args: (True, ""))
    assert VALIDATOR.validate_event(event(VALID_BODY)) == []


def test_event_requires_scope_reviewer_and_sync_attestations(monkeypatch) -> None:
    monkeypatch.setattr(VALIDATOR, "github_issue_exists", lambda *_args: (True, ""))
    incomplete = VALID_BODY.replace("复核人：Reviewer A", "复核人：待项目组指定")
    incomplete = incomplete.replace("- 变更范围：完善 PR 任务和风险门禁。", "- 变更范围：")
    incomplete = incomplete.replace(
        "- [x] 相关 API、OpenAPI、迁移、测试和文档已同步，或已说明不适用",
        "- [ ] 相关 API、OpenAPI、迁移、测试和文档已同步，或已说明不适用",
    )
    errors = VALIDATOR.validate_event(event(incomplete))
    assert any("复核人" in error for error in errors)
    assert any("变更范围" in error for error in errors)
    assert any("相关 API" in error for error in errors)
