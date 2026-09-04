# 正式批准知识（运行时目录）

本目录用于**已审核、可追溯**的知识资料入库，与项目文档中的合成教学卡分离。

## 硬规则

1. **禁止**把未审核 PDF、网页缓存、聊天记录或真实家庭健康资料直接丢进运行时知识目录。
2. 正式资料必须先在受控环境提取为 UTF-8 `.md` / `.txt`，填写来源、许可、版本、权限域、SHA-256、生效窗口与删除责任后再入库。
3. 药品说明书类内容只允许**脱敏摘要**（教学或获批引用范围），不得粘贴受版权保护的说明书全文，不得包含真实患者信息。
4. 入库仍使用 `scripts/ingest_local_knowledge.py`，但清单与 `--source-root` 指向本目录（或子目录），并使用独立的 `--index-version`（例如 `approved-inserts-v1`），不要覆盖演示索引版本。
5. **受控爬虫**只写入 `src/runtime/knowledge/staging/`；必须人工批准并 `promote` 到 `approved/incoming/` 后，才能 dry-run 入库。**禁止 auto_ingest。**

## 成熟产品流水线

```text
crawl/allowlist.json
  → scripts/crawl_knowledge_sources.py   # 定时/手动刷新
  → staging/（draft → reviewed → approved）
  → scripts/promote_knowledge_staging.py
  → approved/incoming/正式知识清单.crawl.json
  → ingest_local_knowledge.py --dry-run → 正式索引
```

Web：管理员「知识文档」页提供到期刷新 / 全量抓取 / 批准 / 拒绝 / 晋升（仍不自动入库）。
CI：`.github/workflows/knowledge-crawl-refresh.yml` 每周刷新夹具到 artifact 并跑爬虫单测。
运营说明：[../crawl/README.md](../crawl/README.md)。

## 推荐布局

```text
src/runtime/knowledge/
  crawl/allowlist.json + fixtures/ + README.md
  staging/                 # 草稿（gitignore 运行产物）
  approved/
    README.md
    审核清单模板.md
    正式知识清单.example.json
    samples/
    incoming/              # 爬虫晋升产物
```

## 入库示例

```powershell
uv run python scripts/crawl_knowledge_sources.py --status
uv run python scripts/crawl_knowledge_sources.py --due-only
uv run python scripts/promote_knowledge_staging.py review --source-id fixture-med-storage --reviewer alice --approve
uv run python scripts/promote_knowledge_staging.py promote --actor-id knowledge-steward
uv run python scripts/ingest_local_knowledge.py `
  --manifest src/runtime/knowledge/approved/incoming/正式知识清单.crawl.json `
  --source-root src/runtime/knowledge/approved `
  --actor-id knowledge-steward `
  --index-version approved-crawl-v1 `
  --dry-run
```

预检查通过后再去掉 `--dry-run`。重复执行应幂等；内容变更时提高文档 `version` 并更新清单哈希。

## 样例说明

`samples/教学用脱敏说明书摘要-示例.md` 是**合成**脱敏摘要，仅演示字段与边界写法，不代表任何真实批准说明书，也不能用于临床决策。
