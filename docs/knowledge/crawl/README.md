# 受控知识爬虫（Continuous refresh）

把公开教学/科普来源**持续刷新进草稿区**，再经人工审核晋升到正式批准路径。这是产品化知识运营流水线，不是开放互联网搜索。

> **给用户的启用步骤：** [联网搜索与知识库刷新启用指南](../../demo/联网搜索与知识库刷新启用指南.md)

## 产品承诺

| 能力 | 行为 |
|---|---|
| 增量刷新 | 按 `refresh_hours` 标记到期来源；CLI/CI/Web 可随时抓取 |
| 变更检测 | SHA-256 比对；抓取报告区分**新来源 / 有更新 / 未变更**；未变保留审核状态，有更新重置为 `draft` 待审 |
| 详情查看 | Web 端 staging 草稿与在用文档均可点开只读详情（正文、来源、SHA、审核轨迹） |
| 人工闸门 | `draft → reviewed → approved → promoted` |
| 正式入库 | 仅 `approved/incoming` + `ingest_local_knowledge.py` |
| 自动入库 | **永远关闭**（`auto_ingest: false`） |
| 模拟更新 | steward 可触发**教学演示** overlay（仅夹具、不出网、不改仓库文件、仍进 staging 待审） |

## 目录

```text
allowlist.json                  # 唯一来源清单 + 抓取策略
fixtures/*.html                 # 离线夹具（CI / 课堂）
../staging/                     # 运行产物（gitignore）
../staging/fixture_overrides/   # 「模拟来源更新」教学 overlay（gitignore）
../approved/incoming/           # 晋升产物（gitignore）
```

## 添加新来源

1. 确认许可允许摘要改写（禁止整页版权复制入库）。
2. 在 `allowlist.json` 增加条目：`id`、`title`、`url`、`license`、`refresh_hours`、`topics`、`enabled`。
3. 远程源：`url` 必须是 HTTPS，且 hostname 落在 `policy.allowed_hosts`；默认 `enabled: false`，启用前写清 `notes`。
4. 离线源：使用 `fixture://knowledge/<file>.html` 并提交对应夹具。
5. 跑夹具抓取与单测：`uv run python scripts/crawl_knowledge_sources.py`。

## 持续更新入口

```powershell
# 本地 / CI（默认仅夹具）
uv run python scripts/crawl_knowledge_sources.py

# 仅抓到期源（按 refresh_hours）
uv run python scripts/crawl_knowledge_sources.py --due-only

# 启用远程（须 allowlist enabled + --live）
uv run python scripts/crawl_knowledge_sources.py --live --due-only
```

- Web：「知识文档」→「知识爬虫 / Staging」（含「一键教学闭环：抓取 → 批准 → 晋升」）
- CI：`.github/workflows/knowledge-crawl-refresh.yml`（每周一 + 手动）

## 失败原因与处理

抓取报告的 `errors` 不返回原始异常、URL 或服务器路径，而是为每个来源提供稳定的
`error`/`code`、人话 `message`、`retryable` 和下一步 `action` 字段。常见结果如下：

| code | 含义 | 是否可重试 |
|---|---|---|
| `UPSTREAM_FORBIDDEN` | 来源返回 403，拒绝抓取 | 否，先检查许可和访问策略 |
| `UPSTREAM_RATE_LIMITED` | 来源返回 429，触发限流 | 是，降低频率后重试 |
| `UPSTREAM_TIMEOUT` | 来源响应超时 | 是，稍后重试或检查站点 |
| `UPSTREAM_UNAVAILABLE` | 来源暂时不可用或网关错误 | 是，稍后重试 |
| `PAGE_TOO_LARGE` | 页面超过大小策略 | 否，检查来源或策略 |
| `FIXTURE_NOT_FOUND` | 本地夹具缺失 | 否，补齐夹具或重建镜像 |
| `HOST_NOT_ALLOWLISTED` | 域名不在允许列表 | 否，修正白名单配置 |

API 运行目录缺少白名单/夹具时，`/knowledge/crawl/status` 和 `/knowledge/crawl/run`
返回 503 `KNOWLEDGE_CRAWL_CONFIG_MISSING`；白名单格式损坏时返回 503
`KNOWLEDGE_CRAWL_CONFIG_INVALID`。两者都不会静默显示成“暂无草稿”。

## 查看抓取内容与已入库文档

- **staging 草稿**：Web 端点击草稿标题或「查看」按钮，可看到抓取正文（Markdown 原文）、来源 URL、
  SHA-256、审核状态、抓取时间、审核备注与批准/拒绝轨迹；接口为
  `GET /api/v1/knowledge/crawl/staging/{source_id}`（steward 权限，与其余爬虫接口一致）。
  详情里明确标注 **staging ≠ 正式检索证据**。
- **在用文档**：dry-run 通过并正式入库后，「在用文档」列表每条可点开只读详情
  （`GET /api/v1/knowledge/documents/{id}`），包含正文、分块预览、版本、许可、哈希与登记轨迹；
  权限过滤与列表一致，越权返回同样的 404。

## 为什么总是「未变更」？

抓取按 SHA-256 比对内容哈希：来源内容没变 → `unchanged`，**属正常现象**（审核状态保留）。
默认离线夹具是仓库内静态文件，因此反复「全量抓取」都会是同一批「未变更」。想看到「有更新」：

1. **教学演示路径（推荐课堂用）**：Web 端点「模拟来源更新（教学演示）」或调用
   `POST /api/v1/knowledge/crawl/simulate-update`（steward 权限）。它只给 `fixture://` 来源
   写一段清晰标注「教学演示模拟更新」的运行时 overlay（位于 gitignore 的
   `staging/fixture_overrides/`，仓库夹具不被修改），下一次抓取即显示「有更新」并把草稿
   重置为 `draft` 重新审核。`?reset=true` 清除 overlay 恢复原文。**不出网、仍进 staging、
   永不 auto_ingest。**
2. **开发者路径**：直接编辑 `fixtures/*.html`（每个夹具头部有 `fixture-version` 注释，
   改注释或正文皆可）并重新抓取。
3. **真实来源路径**：按下节添加远程 HTTPS 源并用 CLI `--live` 刷新，来源页更新后即出现「有更新」。

## 谁可以操作

爬虫 API（`/api/v1/knowledge/crawl/*`）仅对知识管理员开放，其余身份返回 403 `KNOWLEDGE_STEWARD_REQUIRED`，Web 页会显示明确的「需要知识管理员身份」引导：

| 身份 | 说明 |
|---|---|
| `demo-parent` / `knowledge-steward` | 内置演示 steward |
| `demo-*` / `test-*` 前缀 | 演示与测试账号 |
| `KNOWLEDGE_ADMIN_ACTORS` 内账号 | `.env` 中逗号分隔配置，重启 API 后生效 |

API 端 `/knowledge/crawl/run` 强制离线夹具（服务端不出网）；远程刷新只能走 CLI `--live`，且要求 allowlist 中 `enabled: true` 并命中 `policy.allowed_hosts`。**永不 auto_ingest**：晋升后仍须人工执行 `ingest_local_knowledge.py --dry-run` 预检查再正式入库。

Web 端「知识爬虫 / Staging」提供只读的**白名单来源列表**（来自 `GET /knowledge/crawl/status`）：
每个来源显示 夹具/远程、启用状态、`refresh_hours`、是否到期、staging 状态与上次抓取时间，
用于解释「为什么抓的总是这几个来源」。添加真实 HTTPS 来源的步骤见上文「添加新来源」，
启用后在终端执行 `uv run python scripts/crawl_knowledge_sources.py --live --due-only`。

## 状态机

```text
（首次抓取）draft
  → review（可带 notes）
  → approved（steward 批准）
  → promoted（复制到 approved/incoming + 生成 crawl 清单）
内容变更 → 重置为 draft（需重新批准）
```

拒绝：`review --reject` 或 API `approve=false` 且 `reject=true` → `rejected`。
