# PR 任务关联与 Relay Review Bot 工作流

> **当前状态（2026-08-18）**：自动 CI 与 Relay Review Bot 已按项目负责人决定全局停用，
> 仅保留历史规范和手动诊断入口。它们不再是 PR Required Check；合并人必须人工核对任务、
> 测试、风险和回滚。双仓库同步工作流仍独立运行，不得停用。

> 本文规定每个 Pull Request 如何绑定任务、验证交付证据，并通过仓库自有的 Relay Review Bot 检查任务完成度、修改意见和 P0/P1/P2 风险。

日常开发按[PR Review Bot 操作规范](PR%20Review%20Bot%20操作规范.md)执行；本文是门禁和审查协议，操作规范是团队实际执行清单。

## 1. 适用范围

功能 PR 必须绑定一个 GitHub Issue、一个仓库 Story 和对应 FR/NFR。会议记录、维护性或纯资料 PR 可以不绑定 Issue，并进入 Relay Review Bot 白名单；一个功能 PR 只解决一个主要任务，独立任务必须新建 Issue 和 PR。

```text
GitHub Issue 任务
      │
      ├── Story：HCT-xxx
      ├── FR/NFR：FR-xx、NFR-xx
      └── 一个 Pull Request
              ├── Relay Review Bot
              ├── CI / Secret Scan
              └── 合并人核对元数据并完成最终人工复核
```

## 2. PR 必须填写的内容

PR 必须使用 `.github/pull_request_template.md`，填写：

- `Closes #<Issue>`、Story、FR/NFR、负责人和复核人；
- 变更范围、明确非目标、验收标准及代码/测试/文档证据；
- 自动测试、人工验收、部署/迁移影响和回滚方式；
- 数据、隐私、权限、模型、依赖和安全风险；
- Relay Review Bot 是否已运行，以及无法运行时采用的替代人工复核方式。

`Closes #<Issue>` 只填写当前 PR 解决的主要任务。相关但不由本 PR 完成的任务使用 `Related to #<Issue>`，不要混入当前任务验收范围。

## 3. 任务元数据核对

仓库不运行独立的 `Task association and risk metadata` 自动检查。PR 作者填写模板后，Relay Review Bot 可辅助识别缺失项，合并人必须在 merge 前核对：

1. 只有一个 `Closes/Fixes/Resolves #<Issue>`，且对应真实 Issue；
2. 存在仓库中的 `HCT-xxx` Story 文件、FR/NFR、负责人、复核人、变更范围和明确非目标；
3. 验收标准、测试证据、人工验收/演示证据、部署/迁移/回滚部分已填写；
4. 必读工作流、数据安全、AI/医疗安全、视觉确认、需求追踪、API/OpenAPI 同步和高风险复核声明已勾选；
5. 不允许用空白、`TBD`、`TODO`、`通过` 或“见上文”冒充交付证据。

元数据核对不判断业务是否正确。业务完成性由 Relay Review Bot、CI 和合并人的最终检查共同判断；Relay 不可用或被白名单跳过时，合并人承担完整核对责任。

### 3.1 无 Issue 绑定白名单

Relay Review Bot 只审查专用 `Issue` 字段中包含 `Closes/Fixes/Resolves #<编号>` 的 PR。没有该字段或只有 `Related to #<编号>` 的 PR 会由工作流返回成功并跳过中转 API，不消耗 Review Bot 额度；验收正文中偶然出现的 `Closes #...` 不会触发审查。该白名单只针对 Relay Review Bot，不会绕过 CI、Secret Scan、其它 Required Check 或合并人的元数据核对；没有 Issue 的功能 PR 仍应补齐任务绑定。

Relay Review Bot 需要 `contents: read`、`issues: write` 和 `pull-requests: write` 以读取审查上下文并更新一条审查评论。工作流不 checkout 或执行 PR 分支代码，Bot 的写权限仅用于 PR 评论。

## 4. Relay Review Bot 审查协议

`.github/workflows/relay-review-bot.yml` 使用 `pull_request_target` 在可信的默认分支脚本上运行。它读取 PR 元数据、完整 diff、PR 正文、关联 Story 和关键工程规则，调用项目配置的 OpenAI-compatible Chat Completions 中转接口，并在 PR 中更新一条带固定标记的审查评论，同时写入 Actions Summary。

它不是官方 OpenAI Codex Review，也不是 GitHub Copilot Review。它只审查，不执行 PR 中的代码，不拥有仓库写入权限以外的业务权限；本仓库不设置额外第二人 approval，维护者 merge 即代表完成人工复核。

审查结果必须包含以下结构：

```text
## 任务完成结论
完成 / 部分完成 / 未完成 / 无法判断

## 验收标准核对
- [完成/未完成/无法判断] 标准：证据：文件、行或测试定位

## 必须修改
- P0/P1/P2、位置：问题、影响、建议修改方式

## 风险
- P0/P1/P2、领域：描述、缓解措施

## 复核结论
- 是否建议合并；merge 即代表人工复核完成
```

Bot 至少检查：任务和 Story 是否真的完成；验收证据是否可定位；测试、迁移、依赖、API/OpenAPI、文档和回滚是否同步；健康数据和密钥是否泄露；授权、撤权、过期、字段级可见范围和审计；健康事件是否确认、追加写并保护一致性；AI 是否越过证据边界进行诊断、处方、停药、换药或剂量判断。Bot 必须把“待人工复核/尚未把 Story 标为已验证”与技术验收完成度分开：前者不再作为额外合并门槛，除非它本身是明确技术验收标准，否则不能单独把任务判为未完成。权限审查必须先读取事实源，区分家庭 owner 的明确管理员权限与非 owner 照护者的字段级授权，发现规范冲突时列出冲突而不是自行猜测。

阻断规则：仅当任务结论不是“完成”时 Relay Check 因审查结论失败；P0/P1/P2 必须修改项和风险仍按模型返回的真实等级写入评论，但不自动阻断 Relay Check。这样任务完成度是合并审查第一优先级，风险检测作为第二优先级提示。中转 API 网络超时、不可达、408/429/5xx 或返回非法 JSON 时，Job 写入“中转服务不可用”告警并以降级成功结束，不阻塞其它 Required Checks；这不代表任务已通过 AI Review，维护者仍须完成最终人工检查。API 未配置、协议错误、鉴权/权限错误、GitHub 权限或工作流自身错误仍然失败。

## 5. 中转服务配置

在 GitHub 仓库 `Settings → Secrets and variables → Actions` 中配置：

| 类型 | 名称 | 内容 |
|---|---|---|
| Variable | `REVIEW_API_URL` | 完整的 OpenAI-compatible 地址；Responses 例：`https://relay.example/v1/responses`，Chat Completions 例：`https://relay.example/v1/chat/completions` |
| Variable | `REVIEW_API_WIRE` | `responses` 或 `chat_completions`；中转站使用哪种协议就填哪种 |
| Secret | `REVIEW_API_KEY` | 中转服务密钥，不写入仓库、PR、日志或 `.env` |
| Variable | `REVIEW_MODEL` | 中转服务上的模型名，例如 `codex-auto-review` |
| Variable（可选） | `REVIEW_MAX_DIFF_CHARS` | 发送给模型的 diff 上限，默认 120000 |
| Variable（可选） | `REVIEW_API_TIMEOUT_SECONDS` | 请求超时秒数，默认 120 |

中转 Bot 只对同仓库且有 Issue 绑定的 PR 运行，以避免把仓库密钥暴露给 fork PR 或无任务资料 PR。fork PR 仍会运行不需要密钥的 CI；无 Issue 绑定的 PR 由白名单跳过 Bot。

这是明确的网络出口：PR 正文和代码 diff 会发送到配置的中转服务。项目不得在 PR 中提交真实健康数据、药品图片、生产密钥、模型权重、运行日志或其他敏感信息；健康数据默认不出网的产品承诺不因 Review Bot 改变。若中转服务不满足团队隐私要求，不得配置它，改走人工 Review。

## 6. 合并门禁

`master` 应将以下检查设为 Required Checks：

- `Mandatory development docs`；
- `Backend lint, migration and tests`；
- `Frontend typecheck and build`；
- `Secret scan`；

`Task association and risk metadata` 已移除，`Relay Review Bot` 当前为非阻塞辅助检查。功能 PR 的 Issue、Story、FR/NFR、验收证据和风险信息仍是强制流程要求，由合并人在 merge 前核对。

所有 Review 对话必须解决；维护者在合并前检查风险、证据和回滚，merge 动作即代表人工复核完成，不再等待第二位人工 approval。CI 或 Bot 通过不等于业务任务已经完成。

## 7. 未通过处理

1. PR 元数据或证据不完整：作者补充后，由 Relay Review Bot 和合并人重新核对；
2. Relay Review Bot 发现未完成项：在原 PR 分支修复，补充测试/文档/验收证据后重新运行；仅发现风险项时保留评论和真实优先级，由负责人和合并人决定是否处理，不要求为了通过 Check 而修改或降级问题；
3. 中转接口故障：保留不可用告警，不阻塞其它门禁；维护者完成任务、证据、风险和回滚检查后可以合并，服务恢复后再补跑 Review；隐私条件不满足则不得调用中转服务；
4. 需求冲突或事实源不一致：建立 ADR 或评审 Issue，禁止自行猜测；
5. 所有 Required Checks 通过且维护者 merge 后，才能把 Story 更新为“已验证”；merge 记录就是本仓库的人工复核证据。

## 8. 官方 Review 的关闭边界

本仓库不再请求、依赖或声明官方 Codex Review/Copilot Review。历史 PR 中已经产生的官方评论属于 GitHub 审计历史，不能通过提交仓库文件删除；需要关闭未来的官方自动审查，必须由仓库管理员在 GitHub 的 Copilot 自动 Review、规则集或相关应用设置中关闭。仓库内唯一自动 AI 审查入口是 `Relay Review Bot`。
