# 受控知识爬虫（Continuous refresh）

把公开教学/科普来源**持续刷新进草稿区**，再经人工审核晋升到正式批准路径。这是产品化知识运营流水线，不是开放互联网搜索。

## 产品承诺

| 能力 | 行为 |
|---|---|
| 增量刷新 | 按 `refresh_hours` 标记到期来源；CLI/CI/Web 可随时抓取 |
| 变更检测 | SHA-256 比对；未变保留审核状态 |
| 人工闸门 | `draft → reviewed → approved → promoted` |
| 正式入库 | 仅 `approved/incoming` + `ingest_local_knowledge.py` |
| 自动入库 | **永远关闭**（`auto_ingest: false`） |

## 目录

```text
allowlist.json          # 唯一来源清单 + 抓取策略
fixtures/*.html         # 离线夹具（CI / 课堂）
../staging/             # 运行产物（gitignore）
../approved/incoming/   # 晋升产物（gitignore）
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

- Web：「知识文档」→「知识爬虫 / Staging」
- CI：`.github/workflows/knowledge-crawl-refresh.yml`（每周一 + 手动）

## 状态机

```text
（首次抓取）draft
  → review（可带 notes）
  → approved（steward 批准）
  → promoted（复制到 approved/incoming + 生成 crawl 清单）
内容变更 → 重置为 draft（需重新批准）
```

拒绝：`review --reject` 或 API `approve=false` 且 `reject=true` → `rejected`。
