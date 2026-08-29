# HCT-465：RAG 检索接口抽象与评分修复

- Issue：[ #559 ](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/559)
- 历史映射：原 HCT-443《RAG 检索接口抽象与可替换实现》
- 绑定：FR-08、NFR-02、NFR-04
- 角色：后端组员
- 状态：实现完成，待 PR/CI 与维护者人工验收
- 风险：R1；检索仍是本地离线适配器，不引入云端向量服务或新的健康结论

## 目标

抽出稳定的 `retrieve(query, scope) -> ChunkHit[]` 端口，让 API 和本地助手不再依赖具体 SQL/TF-IDF 实现。未来替换为 FAISS、Qdrant 或其他本地适配器时，家庭和成员权限过滤、版本和引用字段保持不变。

## 实现范围

- `src/ai/rag/retrieval.py` 定义 `RetrievalScope`、`ChunkHit` 和 `Retriever` 协议，并提供默认 `LocalKnowledgeRetriever` 适配器。
- API `/knowledge/retrieve` 与本地助手 `retrieve_knowledge` 工具统一通过该端口调用现有本地知识库；查询结果继续携带真实 `chunk_id`、`document_id`、版本、定位和证据正文。
- 适配器边界校验 actor、top-k、分数和结果字段，阻止无效/非有限分数穿透到引用链路。
- 修复同分结果排序不稳定问题，按分数、文档 ID、分块 ID 做确定性排序，使审计缓存和金标回归可复现。
- 不改动权限前置过滤、查询脱敏审计、引用忠实性校验或已有知识内容。

## 验收条件（Given / When / Then）

- Given 同一 actor、家庭和成员范围，When API 或助手切换到默认适配器，Then 返回相同的 chunk/document/version 引用契约。
- Given actor 无权访问某文档，When 执行检索，Then 该文档不会进入结果，也不会因适配器抽象绕过权限过滤。
- Given 两个结果分数相同，When 重复检索，Then 结果顺序按文档 ID 和分块 ID 稳定一致。
- Given 适配器收到空 actor、非法 top-k 或 NaN 分数，When 边界校验执行，Then 返回结构化 `ValueError`，不产生伪造引用。
- Given 本地知识库为空、无授权文档或没有相关结果，When API 调用检索，Then 保持现有结构化降级原因，不访问云端服务。

## 验证命令

```text
uv run pytest tests/unit/test_hct465_rag_retrieval.py tests/unit/test_hct401_knowledge.py tests/unit/test_hct401_knowledge_gold.py -q
uv run ruff check src/ai/rag src/api/app/knowledge.py src/api/app/routes.py src/api/app/tool_call.py tests/unit/test_hct465_rag_retrieval.py
git diff --check
```

## 非目标与回滚

本切片不引入云端 RAG、Embedding 权重、自动入库、真实健康语料或新的医疗回答；也不把检索命中当作健康事实。回滚时 API 和助手可恢复直接调用现有 `app.knowledge.retrieve`，保留现有权限、审计和降级语义。
