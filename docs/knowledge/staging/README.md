# Knowledge staging（抓取草稿区）

本目录存放**受控爬虫**产出的草稿，不是正式 RAG 索引。

## 流水线

```text
allowlist.json → crawl_knowledge_sources.py → staging/
  → promote_knowledge_staging.py（人工批准后）
  → approved/incoming/正式知识清单.crawl.json
  → ingest_local_knowledge.py --dry-run → 正式入库
```

## 硬规则

1. **禁止** `auto_ingest`：爬虫不得直接写入检索索引。
2. 仅抓取 `docs/knowledge/crawl/allowlist.json` 中的来源；默认只用本地 `fixture://` 夹具。
3. 远程 HTTPS 源需 `enabled: true` 且命令加 `--live`。
4. 正文变更以 SHA-256 检测；未变则保留原审核状态。
5. 晋升后仍须独立 `--index-version` 入库。

## 常用命令

```powershell
# 抓取本地夹具（CI / 离线）
uv run python scripts/crawl_knowledge_sources.py

# 运营面板：到期源 / staging 状态
uv run python scripts/crawl_knowledge_sources.py --status

# 仅刷新到期源
uv run python scripts/crawl_knowledge_sources.py --due-only

# 查看 staging
uv run python scripts/promote_knowledge_staging.py list

# 审核并批准
uv run python scripts/promote_knowledge_staging.py review --source-id fixture-med-storage --reviewer alice --approve

# 拒绝草稿
uv run python scripts/promote_knowledge_staging.py review --source-id fixture-med-storage --reviewer alice --reject --notes "许可不清"

# 晋升到 approved/incoming
uv run python scripts/promote_knowledge_staging.py promote --actor-id knowledge-steward
```

更多运营说明见 [../crawl/README.md](../crawl/README.md)。
