# 双仓库同步身份验证

## 测试信息

| 字段 | 值 |
|------|-----|
| 测试时间 | 2026-08-07 |
| 分支 | test/shen-huang-cloud-sync |
| GitHub PR 作者 | Shen-huang-123 |
| Git commit author | zhang <z85963541@qq.com> |
| 推送目标 | 仅 GitHub，不直接推内部仓库 |

## 验证目的

确认《双仓库同步提交说明》中的流程：

1. GitHub 为唯一开发入口，PR 作者为 Shen-huang-123
2. Git 提交身份为 zhang <z85963541@qq.com>
3. 合并后 Actions 自动同步到内部云端
4. 两端 master SHA 一致
5. 内部仓库贡献统计记录到 zhang，而非同步专用推送账号

## 预期结果

- 同步工作流日志显示 PR 作者：Shen-huang-123
- 同步工作流使用 Token Secret：CLOUD_TOKEN_SHEN_HUANG_123
- `git ls-remote` 两端 SHA 完全一致
- 内部仓库 `git log` 显示 author: zhang <z85963541@qq.com>
- 内部仓库贡献统计归入 zhang

## 注意事项

- 不含真实健康数据
- 不含密钥或 Token
- 不含个人隐私信息
