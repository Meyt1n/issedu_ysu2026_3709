# PR Review Bot 操作规范

> HomeCare Twin 团队每一次 Vibe Coding、每一个 PR 和每一次合并都按本规范执行。

## 1. 目标与边界

本规范把“任务是否完成、有哪些缺口、是否存在风险”变成可重复的 PR 流程。Relay Review Bot 是配置在 GitHub Actions 中的中转 AI 审查器，不是官方 OpenAI Codex Review，也不是 GitHub Copilot Review。

Bot 只能辅助审查，不能执行 PR 中的代码，也不能给出诊断、处方、停药、换药或剂量建议。仓库不设置额外第二人 approval，维护者 merge 即代表人工复核完成；PR 正文和代码 diff 会发送到配置的中转 API，因此不得提交真实健康数据、药品图片、密钥、模型权重、日志或缓存。

## 2. 角色分工

| 角色 | 必须完成的工作 |
|---|---|
| 任务负责人 | 建立 Issue/Story，填写 FR/NFR、验收标准、范围、非目标、测试和回滚；实现并修复 PR |
| Relay Review Bot | 检查任务完成度、验收证据、P0/P1/P2 风险，发布一条可更新的 PR 评论并返回状态 |
| 合并人/维护者 | 在 merge 前检查实现是否符合需求、API、隐私、安全、风险和回滚规范；merge 记录即为人工复核证据 |
| 项目负责人 | 分配任务、确认验收、处理阻塞和事实源冲突，合并通过全部门禁的 PR |

负责人和复核人不能混淆。涉及授权、撤权、健康事件、删除、规则、模型、知识或隐私的高风险变更，负责人不得自我复核。

## 3. 开工前操作

### 3.1 领取任务

1. 从 `master` 和[需求追踪矩阵](12-需求追踪矩阵.md)选择一个未完成需求。
2. 确认 Issue 已包含 FR/NFR、用户价值、范围、非目标、风险等级、验收条件、负责人、复核人和预计交付时间。
3. 阅读 `AGENTS.md` 中的 5 个入口文档，再按任务阅读需求、架构、API、数据、隐私、安全、测试、Story 和 ADR。
4. 先写可验证的 Given/When/Then 验收条件，再开始 Vibe Coding。

### 3.2 建立分支

```powershell
git switch master
git pull --rebase origin master
git switch -c feature/<用户名>-<任务简述>
```

分支只解决一个主要 Issue。禁止把真实健康数据、密钥、`.env`、模型权重、日志、缓存或个人备份放入工作区提交。

## 4. 创建 PR 前检查

PR 正文必须使用 `.github/pull_request_template.md`，并逐项填写：

- `- Issue：Closes #<编号>`，且只能出现一个主要任务引用；
- `- Story：HCT-xxx`、`- FR/NFR：FR-xx/NFR-xx`；
- 负责人、复核人、变更范围和明确不做；
- 验收标准、测试证据、人工验收/演示证据、部署/迁移/回滚；
- 数据、隐私、权限、AI 医疗边界、视觉确认边界和网络出口；
- 合并前同步声明及 Relay Review Bot 状态。

本地至少执行：

```powershell
git diff --check
uv run ruff check src/api tests migrations .github/scripts/validate_pr_metadata.py .github/scripts/relay_review_bot.py
uv run pytest
python -m py_compile .github/scripts/validate_pr_metadata.py .github/scripts/relay_review_bot.py
docker compose config --quiet
```

不能运行的检查必须写明原因，不能写“通过”代替命令、环境和结果。

## 5. PR 触发后的检查顺序

PR 创建、更新、重新打开、转为 Ready for review 或正文编辑时，按以下顺序观察检查：

1. `Task association and risk metadata`：读取 PR 元数据，验证 Issue、Story、FR/NFR、范围、证据和安全声明；它不执行 PR 分支代码。
2. `Mandatory development docs`：检查开发入口和必读文档。
3. `Backend lint, migration and tests`：运行后端 lint、迁移和测试。
4. `Frontend typecheck and build`：运行前端类型检查和构建。
5. `Secret scan`：扫描疑似密钥和敏感内容。
6. `Relay Review Bot`：读取 PR 正文、diff、Story 和规则文档，通过配置的中转 API 审查并更新 PR 评论。

Relay Review Bot 只对同仓库且在专用 `Issue` 字段绑定 `Closes/Fixes/Resolves #<编号>` 的 PR 自动运行。无 Issue 绑定的会议记录、维护性或资料 PR 会成功跳过 Bot，不消耗中转额度；Task Gate、CI 和 Secret Scan 仍按原规则运行。fork PR 不获得中转 Secret，仍必须通过不需要外部密钥的门禁。

## 6. 如何阅读 Relay Review Bot 结果

Bot 评论固定包含 5 部分：

1. `任务完成结论`：`complete`、`partial`、`incomplete` 或 `unknown`；
2. `验收标准核对`：每条标准对应可定位的文件、行、测试或演示证据；
3. `必须修改`：列出 P0/P1/P2、位置、问题、影响和建议；
4. `风险`：列出安全、隐私、授权、医疗安全、数据、部署和质量风险；
5. `复核结论`：是否建议合并；本仓库不要求额外第二人 approval，merge 即代表人工复核完成。

`task_completion` 只判断 PR 声明的技术验收标准。PR 正文中的“待人工复核”“复核人尚未确认”或“人工复核前不标记 Story 为已验证”，应记录到“复核结论”，不能单独导致 `partial`；只有明确的人工验收标准未完成，或人工复核发现具体技术标准未满足时，才影响任务完成结论。权限审查还必须遵循事实源：家庭 owner 的明确管理员权限不能仅凭“子女/照护者”角色名称被判为越权，规范冲突应标记为待人工确认。

以下情况会使 `Relay Review Bot` 失败：

- 任务不是 `complete`；
- 未配置 API、接口调用失败、模型返回非法 JSON；
- PR 正文或 diff 命中疑似密钥模式。

P0/P1/P2 必须修改项和风险都保留真实优先级并写入评论，但不自动让 Check 失败；P2 建议可以忽略，P0/P1 由负责人和合并人决定是否处理。不要为了合并而把真实风险改标为 P2；merge 代表维护者已看到并承担本次变更的人工复核责任。

## 7. 失败后的处理

### 7.1 任务门禁失败

修正 PR 正文、Issue、Story、FR/NFR 或必填证据，再推送一次。不要通过修改检查名称、删除工作流或勾选空声明绕过门禁。

### 7.2 Relay Review Bot 失败

1. 先判断是配置/API 故障还是任务未完成；
2. 任务未完成时，按评论中的文件、行和验收标准修复；
3. 增加或更新测试、迁移、OpenAPI、文档和回滚证据；
4. 推送后等待 Bot 重新审查；
5. 只有风险建议时，不要求为了让 Check 变绿而修改代码或降低等级；负责人记录接受、延期或另建 Issue 的决定，不把模型结论当成事实。

### 7.3 高风险问题

P0/P1、越权、数据外泄、未确认视觉结果入库、错误用药判断和不可回滚破坏必须在合并前明确记录风险、影响和回滚方案；它们仍不自动改变 Relay Check，但维护者不得用“merge 即复核”掩盖未理解的问题。

## 8. 合并即人工复核

合并前必须满足：

- 所有 Required Checks 通过；
- 所有 Review conversation 已解决；
- 合并人完成需求、证据、风险和回滚检查；
- 不要求额外第二人 approval；
- 需求、Story、需求追踪矩阵、API/OpenAPI、迁移、测试和文档已同步；
- 没有把 Mock、截图、固定回复或 Notebook 当作完整能力；
- 已确认回滚方式和网络出口影响。

合并后，负责人更新 Story、需求追踪矩阵和交付记录。发现合并后事实源冲突时，先建立 ADR/Issue，不直接覆盖历史事实。

## 9. 中转 API 配置

在 GitHub `Settings → Secrets and variables → Actions` 中配置：

| 类型 | 名称 | 说明 |
|---|---|---|
| Variable | `REVIEW_API_URL` | 完整接口地址，如 `https://relay.example/v1/responses` |
| Variable | `REVIEW_API_WIRE` | `responses` 或 `chat_completions` |
| Variable | `REVIEW_MODEL` | 中转服务上的审查模型名 |
| Secret | `REVIEW_API_KEY` | 只能放 Secret，不能提交到仓库或写入 PR |

当前项目使用 Responses API。API 密钥一旦出现在聊天、截图、日志或提交中，必须立即撤销并重新生成。

## 10. 演练规范

每次修改门禁后，可建立一个“故意不完整”的测试 PR 验证阻断能力：

1. 创建独立测试 Issue，明确写出一个未实现的验收条件；
2. PR 正文按模板完整填写，确保任务格式门禁能够通过；
3. 提交无害的文档或测试夹具，但不实现 Issue 要求的功能；
4. 预期 CI 和任务门禁通过，Relay Review Bot 判定 `partial`/`incomplete` 并失败；
5. 截图或保存 Bot 评论、Actions 日志和检查结果；
6. 关闭测试 PR 和测试 Issue，不得合并测试夹具，不得把测试失败伪装成成功。

演练不得使用真实健康数据、药品图片、生产密钥或真实用户信息。
