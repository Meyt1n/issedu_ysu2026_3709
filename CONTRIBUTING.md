# HomeCare Twin 项目协作规范

所有参与者和 agent 必须先阅读[开发前必读与 Vibe Coding 工作流](docs/vibe-coding/开发前必读与Vibe%20Coding工作流.md)和[PR 任务关联与 Codex Review 工作流](docs/vibe-coding/PR任务关联与Codex%20Review工作流.md)，再遵守 [Vibe Coding 开发约束](docs/vibe-coding/03-Vibe-Coding开发约束.md)、[数据与隐私安全规范](docs/vibe-coding/05-数据与隐私安全规范.md)和对应需求的验收标准。根目录 [`AGENTS.md`](AGENTS.md) 是 agent 的强制入口。

## 0. 开发前必读

任何成员或 agent 在创建分支、阅读代码、规划方案或修改文件前，必须完成[开发前必读与 Vibe Coding 工作流](docs/vibe-coding/开发前必读与Vibe%20Coding工作流.md)。该文档定义 Story、事实优先级、AI 执行协议、测试、PR、验收和双仓库流程；本文件和它发生冲突时，必须先发起评审，不得自行猜测。

## 1. 领取任务

Issue 必须包含需求编号（如 `FR-03`、`NFR-02`）、用户价值、范围与非目标、风险等级、可执行验收条件、负责人、复核人和预计交付时间。没有需求编号或验收条件的任务只允许探索，不得标记为产品功能完成。

成员授权、健康事件、风险规则、数据删除、模型/知识发布属于高风险变更，至少需要第二人复核。

## 2. 分支与提交

默认分支为 `master`。开始任务前先同步远端，再建立任务分支：

```bash
git switch master
git pull --rebase origin master
git switch -c feature/用户名-任务简述
```

分支类型使用 `feature/`、`fix/`、`docs/`、`test/`、`refactor/`、`chore/` 或 `experiment/`。提交示例：

```text
feat: 建立健康事件追加写入接口
fix: 阻止未确认药品进入风险计算
test: 增加跨家庭成员越权回归
docs: 更新视觉复核状态机
```

一次提交只包含一个可解释目标。禁止提交真实健康数据、未经许可的药品图片、`.env`、密钥、模型权重、向量索引、日志、缓存和本地备份。

## 3. 开发闭环

1. 阅读需求、架构、API、领域模型、测试方案和相关 ADR。
2. 先建立失败测试或固定评估样例。
3. 实现最小纵向增量；路由不写 SQL，LLM 不承载确定性规则。
4. 覆盖正常、边界、依赖故障、未登录、越权和撤权场景。
5. 同步 OpenAPI、迁移、数据卡/模型卡及需求追踪矩阵。
6. 执行本地检查，人工审阅完整差异后创建 PR。

视觉或 LLM 变更还需固定测试集对照、失败样例、资源消耗、版本登记和回滚方案。不能通过更换测试集、降低阈值或删除失败样本改善指标。

## 4. Pull Request 门禁

PR 必须说明关联 Issue、Story、FR/NFR、变更范围、测试/评估证据、数据与授权影响、安全边界、AI 使用与人工复核、已知限制、部署/迁移影响和回滚方式，并通过[PR 任务关联与 Codex Review 工作流](docs/vibe-coding/PR任务关联与Codex%20Review工作流.md)定义的自动门禁。

以下情况阻止合并：

- 未确认药品进入正式状态或风险计算；
- LLM 输出诊断、处方、停药、换药或剂量决定；
- 风险卡或证据型回答缺少事实、规则、文档、确认状态或版本；
- 跨家庭越权、撤权不生效或日志泄露敏感正文；
- 数据、模型、规则、提示词或知识版本不可追溯；
- 用 Mock、固定回复、Notebook 或截图冒充完整功能。

## 5. 工程检查

文档改动至少执行：

```powershell
git diff --check
```

代码改动至少执行：

```powershell
uv sync
uv run ruff check src/api tests migrations
uv run pytest
npm ci
npm run check:web
npm run build:web
docker compose config --quiet
```

CI 会重复后端 lint/迁移/测试、前端类型检查/构建和密钥扫描。无法运行的检查要在 PR 中如实说明。

## 6. 发布与双仓库同步

发布单元绑定代码提交、数据库迁移、视觉/OCR 模型、阈值、主数据、规则、知识库、LLM/LoRA、提示词和输出 Schema，并保留上一稳定组合的回滚能力。

本项目同时维护原云端和 GitHub，提交及推送按[双仓库同步提交说明](双仓库同步提交说明.md)执行。禁止强制覆盖共享 `master`。
