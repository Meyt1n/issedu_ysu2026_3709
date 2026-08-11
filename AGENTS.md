# HomeCare Twin Agent Instructions

本文件是 agent 的仓库入口。任何 agent 在阅读、规划、修改、测试或评审本仓库前，必须先完整阅读：

1. [`docs/vibe-coding/开发前必读与Vibe Coding工作流.md`](docs/vibe-coding/开发前必读与Vibe%20Coding工作流.md)
2. [`README.md`](README.md)
3. [`docs/vibe-coding/00-文档导航.md`](docs/vibe-coding/00-文档导航.md)
4. [`docs/vibe-coding/19-项目全生命周期开发流程.md`](docs/vibe-coding/19-项目全生命周期开发流程.md)
5. [`docs/vibe-coding/PR任务关联与 Relay Review Bot 工作流.md`](docs/vibe-coding/PR任务关联与Relay%20Review%20Bot%20工作流.md)
6. [`docs/vibe-coding/PR Review Bot 操作规范.md`](docs/vibe-coding/PR%20Review%20Bot%20操作规范.md)
7. [`docs/vibe-coding/双仓库解耦与独立克隆说明.md`](docs/vibe-coding/双仓库解耦与独立克隆说明.md)

随后根据任务读取对应的需求、架构、API、数据、隐私、安全、测试、Story 和 ADR。不得跳过 mandatory 工作流文档直接生成代码，不得把未验证的方案、Mock 或页面宣称为已完成能力。

Agent 必须遵守：

- 以 GitHub `master` 为开发基线，功能通过 PR 合并，不直接修改共享 `master`；
- GitHub `master` 是当前唯一开发和合并入口；内部仓库已解耦，只能按独立克隆说明单独使用，不得恢复自动同步或跨仓库双推；
- 先绑定 FR/NFR 和 Story，再说明验收条件、风险、允许修改范围和回滚方式；
- 修改前检查工作区并保留他人改动；禁止提交真实健康数据、密钥、日志、模型权重和缓存；
- 高风险的授权、健康事件、删除、规则、模型和知识变更必须在合并前完成风险、测试和回滚审阅；本仓库不要求额外的第二人 approval，维护者执行 merge 即代表完成人工复核；
- 完成后运行对应检查，更新 Story、需求追踪矩阵和相关事实源，并报告可定位证据；
- 发现文档冲突、需求缺口或无法验证时必须停下来说明，不能自行猜测。

## PR Review 规则

每个功能 PR 必须绑定一个 GitHub Issue、一个 Story 和对应 FR/NFR。没有 Issue 绑定的会议记录、维护性或纯资料 PR 可跳过 Relay Review Bot，但仍受 CI 与合并人的元数据核对约束。Relay Review Bot 可用时，必须按[PR 任务关联与 Relay Review Bot 工作流](docs/vibe-coding/PR任务关联与Relay%20Review%20Bot%20工作流.md)核对任务完成度、验收证据和 P0/P1/P2 风险；中转服务故障时只记录不可用告警，不阻塞其它 Required Checks，合并人必须完成替代检查。CI 通过不等于任务完成；合并动作代表本仓库流程中的人工复核完成，不再要求额外第二人 approval。
