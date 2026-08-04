# HomeCare Twin Agent Instructions

本文件是 agent 的仓库入口。任何 agent 在阅读、规划、修改、测试或评审本仓库前，必须先完整阅读：

1. [`docs/vibe-coding/开发前必读与Vibe Coding工作流.md`](docs/vibe-coding/开发前必读与Vibe%20Coding工作流.md)
2. [`README.md`](README.md)
3. [`docs/vibe-coding/00-文档导航.md`](docs/vibe-coding/00-文档导航.md)

随后根据任务读取对应的需求、架构、API、数据、隐私、安全、测试、Story 和 ADR。不得跳过 mandatory 工作流文档直接生成代码，不得把未验证的方案、Mock 或页面宣称为已完成能力。

Agent 必须遵守：

- 以 GitHub `master` 为开发基线，功能通过 PR 合并，不直接修改共享 `master`；
- 先绑定 FR/NFR 和 Story，再说明验收条件、风险、允许修改范围和回滚方式；
- 修改前检查工作区并保留他人改动；禁止提交真实健康数据、密钥、日志、模型权重和缓存；
- 高风险的授权、健康事件、删除、规则、模型和知识变更必须要求第二人复核；
- 完成后运行对应检查，更新 Story、需求追踪矩阵和相关事实源，并报告可定位证据；
- 发现文档冲突、需求缺口或无法验证时必须停下来说明，不能自行猜测。
