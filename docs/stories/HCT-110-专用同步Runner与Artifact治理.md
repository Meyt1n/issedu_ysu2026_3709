# HCT-110：专用同步 Runner 与 Artifact 治理

- GitHub Issue：[ #196](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/196)
- 关联需求：NFR-01、NFR-03、NFR-04、NFR-06
- 阶段：治理增量（不改变既有 P0-W1 至 P0-W8 业务基线）
- 主责：项目负责人
- 复核：维护者合并前复核；本仓库不要求额外第二人 approval
- 风险等级：R2（Runner 具有内部仓库写权限，公开仓库误用会扩大执行风险）
- 前置：HCT-105 双仓库成员身份映射与同步

## 目标

让 GitHub `master` 到内部云端的连续快进同步只在一台专用、带唯一标签
`hct-sync` 的 self-hosted Runner 上执行。Runner 可以是 Linux 或 Windows，平台差异
只影响工具路径，不改变身份预检、快进边界和 SHA 校验；同时关闭 CI 的 Artifact 上传，
避免 Artifact 存储配额和计费影响工作流。

根据项目负责人 2026-08-18 的明确决定，自动 CI 和 Relay Review Bot 也全局停用，
仅保留手动触发入口；`sync-original-cloud.yml` 不停用。

## 范围

1. `.github/workflows/sync-original-cloud.yml` 使用
   `self-hosted`、`hct-sync` 两个标签，并只接受 `master` push 或
   `master` 上的手动运行；不得把不可信 PR/fork 调度到该 Runner。
2. 保留原有成员 Token 映射、全部同步前预检、快进边界、每次 push 后 SHA 核对和
   历史分叉拒绝逻辑。
3. `ci.yml`、历史同步执行和 dry-run workflow 不再调用 `actions/upload-artifact`；测试、
   同步前预检和 SHA 日志仍然保留在工作流日志中。
4. `ci.yml` 与 `relay-review-bot.yml` 只保留 `workflow_dispatch`，不再自动触发或作为
   Required Check；合并人承担本地检查和人工风险复核。
4. 文档说明 Billing、Runner 注册、权限隔离、公开仓库风险、故障恢复和回滚方式。

## Given / When / Then

- Given 一个合并到 GitHub `master` 的 PR，When `sync-original-cloud.yml` 被触发，Then
  只有带有 `self-hosted`、`hct-sync` 的专用 Runner 可以领取同步作业。
- Given 通过 `workflow_dispatch` 选择了非 `master` 分支，When 工作流启动，Then job 被
  跳过，不读取同步 Secrets，也不向内部云端写入。
- Given 任意测试或审计步骤已完成，When 工作流运行结束，Then 不上传 Artifact，工作流
  不因 Artifact 配额、存储或上传服务改变测试/同步结论。
- Given Runner 离线、Billing 仍受限、Secret 缺失或内部历史分叉，When 同步触发，Then
  不伪造成功、不选择其他成员 Token，并保留明确的失败原因供维护者处理。

## Runner 上线操作（不写入仓库）

1. 仓库 Owner 打开 GitHub `Settings → Actions → Runners → New self-hosted runner`，
   按实际机器选择 Linux x64 或 Windows x64，并在专用机器上安装 Runner。
2. 注册时增加自定义标签 `hct-sync`；Runner 必须保持在线，且能访问 GitHub 和内部
   云端 Git URL。不要为 Windows Runner 伪造 `linux` 标签。
3. 使用专用、低权限操作系统账号和独立 Runner 目录；不要把注册令牌、内部 Token 或
   URL 凭据写入仓库、Issue、日志或聊天记录。
4. 该 Runner 只允许运行本工作流。公开仓库不要把 PR/fork 工作流调度到此 Runner；
   当前工作流只在 `master` 上执行同步。
5. Linux Runner 的工具目录固定为 `/data1/ytm/hct-sync-runner/bin`；Windows Runner
   必须在 Runner 环境中配置 `HCT_SYNC_RUNNER_BIN`，其目录至少提供 `python3` 和 `jq`，
   并使用 Git for Windows 的 Bash。Python 版本使用 3.11。
6. Windows Git Bash 可能保留 Python、`jq` 或 `gh` 输出中的 CRLF；工作流在构造
   GitHub API URL、提交引用和云端同步计划前必须剥离 `\r`，否则会出现
   `net/url: invalid control character in URL`。
7. Windows Git Credential Manager 可能复用 Runner 所有者缓存的内部仓库凭据，绕过
   当前 PR 作者对应的 Token。所有内部仓库 `fetch`、`push` 和 `ls-remote` 必须显式
   禁用 credential helper，并通过本次身份计划选中的用户名和 Token 完成认证。
8. Runner 上线后先执行一次 `workflow_dispatch`（分支选择 `master`），确认日志显示
   Runner 标签和完整 SHA 校验，再依赖后续 master push 自动触发。
9. 已明确授权的历史归属修复必须使用一次性历史同步工作流：输入当前内部 SHA、当前
   GitHub SHA 和重放起点。工作流先创建 `hct-sync-backup-<run-id>-<attempt>` 内部标签，
   再用精确旧 SHA 的 `--force-with-lease` 回退，并按登记成员 Token 逐节点恢复；禁止裸
   `--force`。平台若按历史 push 事件累计，重放只能新增正确统计，不能删除旧统计。

## Billing 与恢复边界

账户 Billing 不是仓库文件，不能由 PR 修复。仓库 Owner 需要在 GitHub
`Settings → Billing & licensing` 检查支付方式、预算/额度和付款失败提示。self-hosted
Runner 可以减少 GitHub-hosted runner 依赖，关闭 Artifact 可以避免新增 Artifact 存储，
但不能替代账户级付款限制处理。
Billing 恢复且 Runner 在线后，重新运行最近一次失败的同步；只有 Actions 日志显示最终
`GitHub master SHA = cloud/master SHA` 才能宣布恢复。

## 回滚

- 若专用 Runner 异常，维护者将 `runs-on` 改到另一台已登记、受控且能访问内部仓库的
  `hct-sync` Runner 前，必须先确认权限、网络和账户 Billing；不能临时使用未知 Runner。
- 若 Runner 发现安全问题，立即在 GitHub Runner 设置中停止/删除该 Runner，保留 GitHub
  `master` 和内部 `master` SHA 证据，不强推、不重写历史。
- Artifact 上传可以按需单独恢复，不影响同步身份映射和内部仓库历史；恢复前应确认
  存储额度和付款状态。

## 验收证据

- YAML 静态检查：同步 job 的 Runner 标签、master 条件、CI/Review 手动触发条件以及所有
  Artifact 上传步骤均已关闭。
- `tests/workflows` 中的同步工作流结构回归测试。
- `git diff --check`。
- 合并后的 master Actions：Runner 在线、同步前预检通过、每次 push 后 SHA 核对通过。

本 PR 不把 Billing 未恢复、Runner 未注册或未实际成功同步伪造为完成；在这些外部条件
满足前，HCT-110 保持“待上线验收”。
