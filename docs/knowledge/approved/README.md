# 正式批准知识（非 docs/demo）

本目录用于**已审核、可追溯**的知识资料入库，与 `docs/demo/` 的合成教学卡分离。

## 硬规则

1. **禁止**把未审核 PDF、网页缓存、聊天记录或真实家庭健康资料直接丢进 `docs/demo`。
2. 正式资料必须先在受控环境提取为 UTF-8 `.md` / `.txt`，填写来源、许可、版本、权限域、SHA-256、生效窗口与删除责任后再入库。
3. 药品说明书类内容只允许**脱敏摘要**（教学或获批引用范围），不得粘贴受版权保护的说明书全文，不得包含真实患者信息。
4. 入库仍使用 `scripts/ingest_local_knowledge.py`，但清单与 `--source-root` 指向本目录（或子目录），并使用独立的 `--index-version`（例如 `approved-inserts-v1`），不要覆盖演示索引版本。

## 推荐布局

```text
docs/knowledge/approved/
  README.md                 # 本说明
  正式知识清单.example.json # 清单字段示例
  samples/                  # 仅含合成/脱敏教学摘要样例
    教学用脱敏说明书摘要-示例.md
```

## 入库示例

```powershell
uv run python scripts/ingest_local_knowledge.py `
  --manifest docs/knowledge/approved/正式知识清单.json `
  --source-root docs/knowledge/approved `
  --actor-id knowledge-steward `
  --index-version approved-inserts-v1 `
  --dry-run
```

预检查通过后再去掉 `--dry-run`。重复执行应幂等；内容变更时提高文档 `version` 并更新清单哈希。

## 样例说明

`samples/教学用脱敏说明书摘要-示例.md` 是**合成**脱敏摘要，仅演示字段与边界写法，不代表任何真实批准说明书，也不能用于临床决策。
