# 本地 RAG 入库与运行

本仓库的本地 RAG 由三部分组成：批准知识清单、版本化文档/分块索引、权限前置后的检索与引用校验。模型只能使用工具返回的可访问片段，不能把模型记忆或未命中的内容伪装成知识库事实。

当前仓库提供一份只含合成演示内容的清单：`本地RAG知识清单.json`。它引用同目录下的六张教学演示知识卡，不含真实家庭健康数据，也不代表临床指南或个体化用药建议：

| 文件 | 主题 | 文档版本 |
|---|---|---|
| `家庭用药安全演示知识.md` | 药品身份核对、规则演示口径、计划与照护边界 | `demo-cn-en-v1` |
| `家庭药品存放与过期处置教学卡.md` | 存放常识、儿童安全、过期药识别与处置 | `demo-cn-en-v2` |
| `过敏信息记录与授权分享教学卡.md` | 过敏记录字段、授权边界、最小必要分享 | `demo-cn-en-v2` |
| `血压血糖居家记录观察教学卡.md` | 指标记录与观察方法，不解读数值高低 | `demo-cn-en-v2` |
| `居家照护沟通与紧急联络教学卡.md` | 何时联系医务人员/急救、联络准备清单 | `demo-cn-en-v2` |
| `药品包装识别与人工复核教学卡.md` | 多证据识别、四状态、人工复核要点 | `demo-cn-en-v2` |

全部知识卡都是自写合成教学文，标注「教学演示、非诊断、非处方」；不得把它们扩展成剂量、停药、换药或诊断结论，也不得复制受版权保护的说明书全文。

## 首次准备

在仓库根目录执行：

```powershell
uv sync --frozen
uv run alembic upgrade head
```

如果使用默认 SQLite 开发库，命令会使用 `.env` 或应用默认的 `homecare-dev.sqlite3`。如果使用演示启动脚本，先按 `scripts/start-demo.ps1` 启动 MySQL/API，再在同一个仓库目录运行入库命令。

## 预检查

先做 dry-run。它只验证清单状态、路径、扩展名、权限字段、文件编码和 SHA-256，不写入数据库：

```powershell
uv run python scripts/ingest_local_knowledge.py `
  --manifest docs/demo/本地RAG知识清单.json `
  --source-root docs/demo `
  --actor-id demo-admin `
  --index-version demo-cn-en-v2 `
  --dry-run
```

预期输出中的 `ok` 为 `true`，文档动作是 `create`（首次）或 `skip`（已经入库）。如果出现 `MANIFEST_NOT_APPROVED`、`PATH_OUTSIDE_SOURCE_ROOT` 或 `CONTENT_HASH_MISMATCH`，必须先修正来源清单，不要绕过校验。

## 正式入库

预检查通过后执行：

```powershell
uv run python scripts/ingest_local_knowledge.py `
  --manifest docs/demo/本地RAG知识清单.json `
  --source-root docs/demo `
  --actor-id demo-admin `
  --index-version demo-cn-en-v2
```

命令会在同一事务中完成文档登记、自动分块和索引快照。分块按 Markdown 章节切分（超长章节回退为带重叠的字符窗口），`locator` 会带上 `section:<章节名>` 前缀，便于引用定位。重复执行同一清单不会重复插入；如果同一 `title/source/version` 的原文、许可或权限发生变化，会报 `DOCUMENT_VERSION_CONFLICT`，应提高文档版本并重新做清单审核。索引版本已经存在但内容发生变化时会报 `INDEX_VERSION_CONFLICT`，不能覆盖旧快照。

在已经用旧清单（`demo-cn-en-v1` 索引）入库过的数据库上执行本清单时，原有文档会被 `skip`，五张新教学卡会被 `create`，并生成新的 `demo-cn-en-v2` 索引快照；旧索引快照保留用于审计。分块策略更新后，如需让旧文档也使用章节分块，应在干净数据库上全量重建并使用新的索引版本。

## 检索验证

API 启动后可以使用：

```powershell
$body = @{ query = '过期药品怎么处置'; top_k = 3 } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/knowledge/retrieve `
  -Headers @{ 'X-Actor-Id' = 'demo-admin' } `
  -ContentType 'application/json' `
  -Body $body
```

正常结果应包含 `document_id`、`version`、`chunk_id`、`locator`、`text` 和 `score`，`locator` 形如 `section:4. 过期药品识别与处置|chars:415-650`。检索评分是块级平滑 TF-IDF：词频取次线性（1 + ln tf），并按查询词覆盖度加权，覆盖更多查询词的块排前。查询没有命中时返回 `degraded=true`、`degrade_reason=NO_RELEVANT_RESULTS`；空白或纯停用词查询返回 `EMPTY_QUERY`；没有权限时返回 `NO_AUTHORISED_DOCUMENTS`。这些状态都不能交给模型补写事实。

其它主题的验证查询示例：`药品身份核对`、`过敏信息记录和分享注意什么`、`血压血糖记录观察`、`什么时候需要联系急救`、`药盒包装识别人工复核`，预期各自命中对应教学卡（与 `tests/unit/test_local_knowledge_ingest.py` 的主题断言一致）。

## 接入助手时的边界

- `retrieve_knowledge` 的家庭和成员范围由后端绑定，模型不能改写调用者的范围。
- 最终回答中的知识引用必须来自本轮工具返回的 `document_id/version/chunk_id`。
- 删除文档后，分块会从本地检索候选中移除；异常时回退到结构化事实/规则卡，不回退到云端健康上下文。
- 本文只解决本地入库、检索和审计闭环，不等于完成知识质量审核、临床适用性评估或 RAG 效果验收。

## 换成真实批准资料

不要直接把 PDF、网页缓存、聊天记录或真实家庭健康资料放进 `docs/demo`。为每份脱敏且获准使用的文本建立独立清单，填写来源、许可、版本、权限域和 SHA-256；哈希按脚本读取后的 UTF-8 文本计算（跨平台换行会规范化），不要直接填原始文件字节哈希。用新的 `--index-version` 入库，并保留审核记录、删除方式和回滚版本。PDF 应先在受控环境提取为纯文本并单独复核，当前脚本只接受 UTF-8 的 `.md`/`.txt`。
