# PR 任务关联与 Codex Review 工作流

> 本文规定每个 Pull Request 如何绑定一个任务、如何验证交付证据，以及如何使用 Codex Review 发现未完成项和风险。

## 1. 适用范围

每个提交到 GitHub `master` 的 PR 都必须绑定一个 GitHub Issue 任务和一个仓库 Story。PR 可以包含多个提交，但一个 PR 只解决一个主要任务；拆分出的独立任务必须新建 Issue 和 PR。

任务、Story、FR/NFR 和 PR 的关系如下：

```text
GitHub Issue 任务
      │
      ├── Story：HCT-xxx
      ├── FR/NFR：FR-xx、NFR-xx
      └── 一个 Pull Request
              ├── 自动任务门禁
              ├── Codex Review
              ├── CI / Secret Scan
              └── 第二人人工复核
```

## 2. 开发者提交 PR 前必须填写

PR 必须使用仓库的 `.github/pull_request_template.md`，至少填写：

- `Closes #<Issue>`、Story、FR/NFR；
- 变更范围和明确非目标；
- 每一项验收标准及对应代码、测试或文档证据；
- 自动测试、人工验收、部署/迁移影响和回滚方式；
- 数据、隐私、权限、模型、依赖和安全风险；
- 负责人、复核人，以及是否需要第二人复核。

`Closes #<Issue>` 只填写当前 PR 解决的主要任务。合并后 GitHub 会自动关闭该 Issue；相关但不由本 PR 完成的任务使用 `Related to #<Issue>`，不要混入当前任务的验收范围。

## 3. 自动任务门禁

`.github/workflows/pr-task-governance.yml` 在 PR 创建、正文或提交更新、重新打开和转为 Ready for review 时运行，当前只读检查，不修改 PR 内容。它至少验证：

1. PR 正文存在且只包含一个 `Closes/Fixes/Resolves #<Issue>` 任务引用；
2. PR 正文存在 `HCT-xxx` Story，且仓库中存在对应 Story 文件；
3. PR 正文存在 FR/NFR、负责人、复核人、变更范围和明确非目标；
4. 验收标准、测试证据、人工验收/演示证据、部署/迁移/回滚四个部分均已填写；
5. 必读工作流、数据安全、AI/医疗安全边界、未确认视觉结果边界、需求追踪矩阵、API/OpenAPI 同步和高风险复核声明已勾选；
6. 不允许用空白、`TBD`、`TODO`、`通过` 或“见上文”冒充交付证据；任务引用必须对应真实 Issue。

自动门禁只检查交付格式和最低证据，不判断业务是否正确。业务完成性由 Codex Review、CI 和人工复核共同判断。

## 4. Codex Review 审查协议

仓库启用 Codex Code Review 后，PR 从 Draft 转为 Ready for review 时自动触发；也可以在 PR 对话中发送：

```text
@codex review
```

需要专项检查时使用：

```text
@codex review for task completion, security, privacy, authorization, and medical-safety risks
```

Codex Review 必须先阅读：

1. `AGENTS.md`；
2. PR 正文和关联 GitHub Issue；
3. PR 中声明的 Story、FR/NFR 和对应事实源；
4. 当前 PR 的完整 diff、测试和相关配置。

审查结果必须按以下结构输出：

```text
## 任务完成结论
完成 / 部分完成 / 未完成

## 验收标准核对
- [完成/未完成] 标准：证据：文件或测试定位

## 必须修改
- 文件、行或模块：问题、影响、建议修改方式

## 风险
- P0：可导致数据泄露、越权、错误健康结论或不可回滚破坏
- P1：影响核心功能、数据一致性、审计或部署安全
- P2：一般质量、可维护性或文档缺口

## 复核结论
是否需要第二位复核人；是否建议合并
```

审查时必须特别关注：

- PR 是否真的完成关联任务，而不是只增加文档、Mock 或通过测试；
- 授权、撤权、过期、跨家庭访问、字段级可见范围和审计；
- 健康事件是否经过确认、追加写、事务保护和状态投影；
- 健康数据、真实图片、密钥、日志、模型权重和缓存是否进入仓库或网络；
- AI 是否越过证据边界进行诊断、处方、停药、换药或剂量判断；
- 迁移、依赖、网络出口、错误处理和回滚是否有证据；
- 需求、Story、API、OpenAPI、测试和实现是否互相矛盾。

Codex 的“通过”不能替代人工审批；Codex 发现的问题也不能在没有验证的情况下直接当作事实。任何高风险授权、健康事件、删除、规则、模型、知识或隐私变更，都必须由第二名人工复核人确认。

## 5. 合并门禁

项目负责人应在 GitHub `master` 上启用以下保护条件：

- `HomeCare Twin CI` 全部通过；
- `Task association and risk metadata` 通过（工作流名称为 `PR task and risk governance`）；
- 至少一名非提交者人工审批；
- 高风险变更至少两名人工复核人；
- 相关 CODEOWNERS 审批（仓库配置完成后启用）；
- 所有 Review 对话已解决；
- 禁止直接推送、强制推送和绕过门禁合并。

Codex Review 当前作为审查意见来源和风险提示，不作为唯一合并依据。若未来要把 Codex 结论转为 Required Status Check，必须使用受控的可信服务，并记录模型版本、输入范围、结论和人工复核；不能把不稳定的自然语言评论直接当作阻断信号。

## 6. 隐私与安全边界

- 仓库不得提交真实家庭健康数据、药品图片、账号密码、生产密钥、模型权重和运行日志；
- 治理门禁可以使用 `pull_request_target` 读取 PR 元数据，但必须只 checkout 默认分支上的可信校验脚本，不得 checkout/执行 PR 分支代码，也不得暴露密钥；
- GitHub Actions 默认只授予 `contents: read` 和 `pull-requests: read`；
- 任何把源代码或数据发送给外部模型/服务的步骤都必须单独评审；
- Gitleaks、依赖审计和人工隐私复核不能被 Codex Review 替代；
- 发现数据外发、越权或医疗安全风险时，先停止合并，建立 Issue 并指定复核人。

## 7. 未通过时的处理

1. 自动门禁失败：先修正 PR 元数据和证据，不得关闭检查冒充通过；
2. Codex 发现未完成项或风险：在原 PR 分支修改，补充测试/文档/验收证据后重新 Review；
3. 需求冲突或事实源不一致：建立 ADR 或评审 Issue，禁止自行猜测；
4. 高风险问题：标记为 P0/P1，暂停合并并等待第二人复核；
5. 只有所有门禁和人工复核通过后，才能将 Story 从“进行中/待验收”更新为“已验证”。

## 8. 账号侧启用步骤

仓库文件只能提供审查规则，不能代替 Codex 与 GitHub 的账号授权。项目负责人还需要：

1. 在 Codex 中连接 GitHub 账号；
2. 为 `Meyt1n/issedu_ysu2026_3709` 开启 Code Review；
3. 新建一个 Draft PR，补齐模板后转为 Ready for review；
4. 确认 Codex 在 PR 中发布 Review；
5. 在仓库设置中把 CI 和任务门禁设为 `master` 的 Required Checks，并启用人工审批和对话解决。

首次启用后，用一个无害的文档 PR 验证流程，不要用真实健康数据或生产密钥测试。
