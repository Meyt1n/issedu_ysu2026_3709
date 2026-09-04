# 知识库与RAG设计

> 本文档是家健镜系统知识库与检索增强生成（RAG）的完整设计说明，覆盖文档管理、分块策略、向量化、检索、重排序、引用生成、降级策略。面向后端开发者和算法工程师，作为知识库实现的权威依据。

## 1. 知识库概述

### 1.1 设计目标

1. **可信来源**：只使用已批准的健康知识文档
2. **可追溯**：每个回答都有引用来源
3. **隐私保护**：检索在家庭服务器本地完成
4. **可扩展**：支持多种文档格式和数据源
5. **降级优雅**：检索失败时如实告知，不编造

### 1.2 知识来源

| 来源 | 类型 | 说明 |
| --- | --- | --- |
| 药品说明书 | PDF | 药品用法、副作用、禁忌 |
| 疾病指南 | PDF/网页 | 权威医学指南 |
| 健康科普 | Markdown | 家庭健康知识 |
| 用药常识 | Markdown | 用药注意事项 |
| 季节养生 | Markdown | 季节性健康建议 |

### 1.3 处理流程

```
文档上传
    ↓
文档解析（PDF/Markdown/HTML）
    ↓
文档分块（按语义/固定大小）
    ↓
向量化（Embedding 模型）
    ↓
向量存储（SQLite pgvector / FAISS）
    ↓
用户提问
    ↓
查询向量化
    ↓
相似度检索（Top-K）
    ↓
重排序（Reranker，可选）
    ↓
构建 Prompt（问题 + 检索结果）
    ↓
LLM 生成回答
    ↓
返回回答 + 引用
```

## 2. 文档管理

### 2.1 文档表

```sql
CREATE TABLE knowledge_documents (
    document_id UUID PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    category VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    source VARCHAR(200) NOT NULL,
    license VARCHAR(200),
    index_version VARCHAR(50) NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    summary TEXT,
    chunk_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 2.2 文档状态

| 状态 | 说明 | 可检索 |
| --- | --- | --- |
| pending | 待审核 | 否 |
| approved | 已批准 | 是 |
| rejected | 已拒绝 | 否 |
| archived | 已归档 | 否 |

### 2.3 文档上传

```python
async def upload_document(
    file: UploadFile,
    title: str,
    category: str,
    source: str,
    db: AsyncSession,
) -> KnowledgeDocument:
    # 1. 校验文件
    if file.content_type not in ("application/pdf", "text/markdown", "text/html"):
        raise BusinessError("INVALID_FORMAT", "只支持 PDF/Markdown/HTML")

    # 2. 保存文件
    file_path = await save_upload_file(file)

    # 3. 创建文档记录（pending 状态）
    doc = KnowledgeDocument(
        title=title,
        category=category,
        status="pending",
        source=source,
        index_version=generate_index_version(),
        effective_at=datetime.now(),
    )
    db.add(doc)
    await db.commit()

    # 4. 异步解析和索引
    asyncio.create_task(index_document(doc.document_id, file_path))

    return doc
```

### 2.4 文档审核

```python
async def approve_document(document_id: str, db: AsyncSession) -> KnowledgeDocument:
    doc = await db.get(KnowledgeDocument, document_id)
    if doc.status != "pending":
        raise BusinessError("INVALID_STATUS", f"文档状态为 {doc.status}，无法审核")

    doc.status = "approved"
    doc.updated_at = datetime.now()
    await db.commit()
    return doc
```

## 3. 文档分块

### 3.1 分块策略

| 策略 | 说明 | 适用场景 |
| --- | --- | --- |
| 固定大小 | 每块 500 token，重叠 50 token | 通用 |
| 语义分块 | 按段落/标题分割 | 结构化文档 |
| 递归分块 | 按标题→段落→句子递归 | Markdown/HTML |

### 3.2 分块实现

```python
class DocumentChunker:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_markdown(self, content: str) -> list[Chunk]:
        # 按标题分割
        sections = re.split(r'(^#{1,3} .+$)', content, flags=re.MULTILINE)

        chunks = []
        current_title = ""
        current_content = ""

        for i, section in enumerate(sections):
            if re.match(r'^#{1,3} ', section):
                # 新标题，保存上一块
                if current_content.strip():
                    chunks.extend(self._split_if_needed(
                        current_title, current_content
                    ))
                current_title = section.strip()
                current_content = ""
            else:
                current_content += section

        if current_content.strip():
            chunks.extend(self._split_if_needed(current_title, current_content))

        return chunks

    def _split_if_needed(self, title: str, content: str) -> list[Chunk]:
        # 按 token 估算（中文 1 字 ≈ 1.5 token）
        estimated_tokens = len(content) * 1.5

        if estimated_tokens <= self.chunk_size:
            return [Chunk(title=title, content=content.strip(), order=0)]

        # 超过大小，按段落分割
        paragraphs = content.split('\n\n')
        chunks = []
        current_text = ""
        order = 0

        for para in paragraphs:
            if len(current_text) + len(para) > self.chunk_size / 1.5:
                if current_text.strip():
                    chunks.append(Chunk(title=title, content=current_text.strip(), order=order))
                    order += 1
                    # 重叠
                    current_text = current_text[-self.chunk_overlap:] + para
                else:
                    current_text = para
            else:
                current_text += "\n\n" + para

        if current_text.strip():
            chunks.append(Chunk(title=title, content=current_text.strip(), order=order))

        return chunks
```

### 3.3 分块表

```sql
CREATE TABLE knowledge_chunks (
    chunk_id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES knowledge_documents(document_id) ON DELETE CASCADE,
    title VARCHAR(500),
    content TEXT NOT NULL,
    "order" INTEGER NOT NULL,
    token_count INTEGER NOT NULL,
    embedding vector(1536),  -- PostgreSQL pgvector
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chunks_document ON knowledge_chunks(document_id, "order");
CREATE INDEX idx_chunks_embedding ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops);
```

## 4. 向量化

### 4.1 Embedding 模型

```python
class EmbeddingService:
    def __init__(self, model_name: str = "text-embedding-3-small", base_url: str | None = None):
        self.model_name = model_name
        self.base_url = base_url
        self.dimension = 1536

    async def embed(self, text: str) -> list[float]:
        # 使用 OpenAI 兼容 API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url or 'https://api.openai.com/v1'}/embeddings",
                json={"model": self.model_name, "input": text},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()["data"][0]["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # 批量向量化
        results = []
        for i in range(0, len(texts), 10):  # 每批 10 条
            batch = texts[i:i+10]
            embeddings = await asyncio.gather(*[self.embed(t) for t in batch])
            results.extend(embeddings)
        return results
```

### 4.2 本地模型（可选）

```python
class LocalEmbeddingService:
    '''使用本地模型（如 sentence-transformers），数据不出网'''
    def __init__(self, model_path: str):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_path)
        self.dimension = self.model.get_sentence_embedding_dimension()

    async def embed(self, text: str) -> list[float]:
        # 在线程池中运行（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None, lambda: self.model.encode(text).tolist()
        )
        return embedding
```

## 5. 向量存储

### 5.1 PostgreSQL pgvector

```python
async def search_similar(
    query_embedding: list[float],
    top_k: int = 5,
    document_ids: list[str] | None = None,
    db: AsyncSession,
) -> list[tuple[KnowledgeChunk, float]]:
    # 余弦相似度搜索
    query = select(
        KnowledgeChunk,
        func.cosine_distance(KnowledgeChunk.embedding, query_embedding).label("distance"),
    ).where(KnowledgeChunk.document_id.in_(
        select(KnowledgeDocument.document_id).where(
            KnowledgeDocument.status == "approved"
        )
    ))

    if document_ids:
        query = query.where(KnowledgeChunk.document_id.in_(document_ids))

    query = query.order_by("distance").limit(top_k)
    result = await db.execute(query)

    return [(chunk, 1 - distance) for chunk, distance in result.all()]
```

### 5.2 SQLite 方案（家庭部署）

```python
class SQLiteVectorStore:
    '''SQLite 不支持向量，使用 FAISS 或 sqlite-vss'''
    def __init__(self, index_path: str):
        import faiss
        self.index = faiss.read_index(index_path)
        self.chunk_ids: list[str] = []  # 索引到 chunk_id 的映射

    async def search(self, query_embedding: list[float], top_k: int = 5):
        import numpy as np
        query_array = np.array([query_embedding]).astype('float32')
        distances, indices = self.index.search(query_array, top_k)

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self.chunk_ids):
                results.append((self.chunk_ids[idx], 1 - distances[0][i]))
        return results
```

## 6. 检索流程

### 6.1 检索服务

```python
class KnowledgeSearchService:
    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        db: AsyncSession,
    ):
        self.embedding = embedding_service
        self.vector_store = vector_store
        self.db = db

    async def search(
        self,
        query: str,
        top_k: int = 5,
        member_id: str | None = None,
    ) -> KnowledgeSearchResult:
        # 1. 检查是否有已批准文档
        doc_count = await self._count_approved_documents()
        if doc_count == 0:
            return KnowledgeSearchResult(
                results=[],
                degraded=DegradedInfo(
                    code="NO_AUTHORISED_DOCUMENTS",
                    message="当前没有已批准的知识文档",
                ),
            )

        # 2. 查询向量化
        query_embedding = await self.embedding.embed(query)

        # 3. 相似度检索
        raw_results = await self.vector_store.search(query_embedding, top_k=top_k * 2)

        if not raw_results:
            return KnowledgeSearchResult(
                results=[],
                degraded=DegradedInfo(
                    code="NO_RELEVANT_RESULTS",
                    message="没有找到相关内容",
                ),
            )

        # 4. 过滤低相似度
        threshold = 0.5
        filtered = [(chunk_id, score) for chunk_id, score in raw_results if score >= threshold]

        if not filtered:
            return KnowledgeSearchResult(
                results=[],
                degraded=DegradedInfo(
                    code="NO_RELEVANT_RESULTS",
                    message="没有找到相关内容",
                ),
            )

        # 5. 重排序（可选）
        # reranked = await self.reranker.rerank(query, filtered)

        # 6. 构建结果
        results = []
        for chunk_id, score in filtered[:top_k]:
            chunk = await self.db.get(KnowledgeChunk, chunk_id)
            doc = await self.db.get(KnowledgeDocument, chunk.document_id)
            results.append(SearchResult(
                document_id=doc.document_id,
                chunk_id=chunk.chunk_id,
                title=chunk.title or doc.title,
                score=score,
                snippet=self._generate_snippet(chunk.content, query),
                index_version=doc.index_version,
            ))

        return KnowledgeSearchResult(results=results, degraded=None)
```

### 6.2 摘要生成

```python
    def _generate_snippet(self, content: str, query: str, max_length: int = 200) -> str:
        # 找到查询词在内容中的位置
        query_words = query.split()
        best_pos = 0
        best_score = 0

        for word in query_words:
            pos = content.lower().find(word.lower())
            if pos >= 0:
                best_pos = pos
                break

        # 截取上下文
        start = max(0, best_pos - 50)
        end = min(len(content), start + max_length)
        snippet = content[start:end]

        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."

        return snippet
```

## 7. RAG 生成

### 7.1 Prompt 构建

```python
class RAGService:
    SYSTEM_PROMPT = '''你是家健镜健康助手，基于提供的健康知识回答用户问题。

规则：
1. 只使用提供的参考资料回答问题
2. 如果参考资料中没有答案，明确说"根据现有资料无法回答"
3. 回答中引用来源，格式：[文档标题]
4. 不提供医疗诊断或处方建议
5. 建议用户咨询医生或药师
6. 用简洁、易懂的语言回答

参考资料：
{context}
'''

    def build_prompt(self, query: str, search_results: list[SearchResult]) -> str:
        context_parts = []
        for i, result in enumerate(search_results, 1):
            context_parts.append(f"[{i}] {result.title}\n{result.snippet}")

        context = "\n\n".join(context_parts)
        return self.SYSTEM_PROMPT.format(context=context)
```

### 7.2 生成回答

```python
    async def generate(
        self,
        query: str,
        search_results: list[SearchResult],
        llm_service: LLMService,
    ) -> RAGResponse:
        if not search_results:
            return RAGResponse(
                content="根据现有资料无法回答这个问题。建议咨询医生或药师。",
                citations=[],
                evidence_complete=False,
                degraded=True,
            )

        prompt = self.build_prompt(query, search_results)

        # 调用 LLM
        response = await llm_service.chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ],
            stream=False,
        )

        # 提取引用
        citations = self._extract_citations(response.content, search_results)

        return RAGResponse(
            content=response.content,
            citations=citations,
            evidence_complete=True,
            model_version=response.model,
        )
```

### 7.3 引用提取

```python
    def _extract_citations(
        self,
        answer: str,
        search_results: list[SearchResult],
    ) -> list[Citation]:
        citations = []
        # 匹配 [1]、[2] 等引用标记
        ref_numbers = re.findall(r'\[(\d+)\]', answer)

        for num in ref_numbers:
            idx = int(num) - 1
            if 0 <= idx < len(search_results):
                result = search_results[idx]
                citations.append(Citation(
                    document_id=result.document_id,
                    chunk_id=result.chunk_id,
                    version=result.index_version,
                    title=result.title,
                ))

        return citations
```

## 8. 流式生成

### 8.1 SSE 流式响应

```python
async def generate_stream(
    query: str,
    search_results: list[SearchResult],
    llm_service: LLMService,
):
    prompt = build_prompt(query, search_results)

    # 发送 agent_stage 事件
    yield StreamChunk(event="agent_stage", data={"stage": "searching", "message": "正在检索知识..."})
    yield StreamChunk(event="evidence_preview", data={
        "type": "knowledge",
        "preview": search_results[0].title if search_results else "",
    })

    # 流式生成
    yield StreamChunk(event="agent_stage", data={"stage": "generating", "message": "正在生成回答..."})

    async for chunk in llm_service.chat_stream(
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": query}],
    ):
        yield StreamChunk(event="content_delta", data={"delta": chunk.content})

    # 完成
    yield StreamChunk(event="done", data={
        "reply_id": generate_id(),
        "citations": [c.dict() for c in citations],
        "model_version": model_version,
    })
```

## 9. 降级策略

### 9.1 降级场景

| 场景 | 降级方式 |
| --- | --- |
| 无已批准文档 | 返回 NO_AUTHORISED_DOCUMENTS |
| 索引为空 | 返回 EMPTY_INDEX |
| 无相关结果 | 返回 NO_RELEVANT_RESULTS |
| Embedding 服务不可用 | 返回 KNOWLEDGE_UNAVAILABLE |
| LLM 不可用 | 返回检索结果，不生成回答 |
| 检索超时 | 返回缓存结果或降级提示 |

### 9.2 降级实现

```python
async def safe_search(query: str, db: AsyncSession) -> KnowledgeSearchResult:
    try:
        return await knowledge_service.search(query, db=db)
    except EmbeddingServiceError:
        return KnowledgeSearchResult(
            results=[],
            degraded=DegradedInfo(
                code="KNOWLEDGE_UNAVAILABLE",
                message="知识检索服务暂时不可用",
            ),
        )
    except Exception as e:
        logger.error("知识检索失败", error=str(e))
        return KnowledgeSearchResult(
            results=[],
            degraded=DegradedInfo(
                code="KNOWLEDGE_UNAVAILABLE",
                message="知识检索服务暂时不可用",
            ),
        )
```

## 10. 索引管理

### 10.1 索引重建

```python
async def rebuild_index(document_id: str, db: AsyncSession):
    # 1. 删除旧分块
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))

    # 2. 重新解析和分块
    doc = await db.get(KnowledgeDocument, document_id)
    chunks = chunk_document(doc.file_path)

    # 3. 向量化
    embeddings = await embedding_service.embed_batch([c.content for c in chunks])

    # 4. 存储
    for chunk, embedding in zip(chunks, embeddings):
        db.add(KnowledgeChunk(
            document_id=document_id,
            title=chunk.title,
            content=chunk.content,
            order=chunk.order,
            token_count=chunk.token_count,
            embedding=embedding,
        ))

    doc.chunk_count = len(chunks)
    doc.index_version = generate_index_version()
    await db.commit()
```

### 10.2 索引版本

- 每次文档更新生成新的 index_version
- 检索结果返回 index_version
- 确认风险时验证 index_version（防止引用过时内容）

## 11. 质量评估

### 11.1 评估指标

| 指标 | 说明 | 目标 |
| --- | --- | --- |
| 检索准确率 | 相关文档在 Top-K 中的比例 | ≥80% |
| 回答准确率 | 回答与参考资料一致 | ≥90% |
| 引用准确率 | 引用与回答内容相关 | ≥85% |
| 无答案识别率 | 正确识别无答案的比例 | ≥90% |
| 响应时间 | 检索+生成总时间 | <10s |

### 11.2 评估数据集

```python
# 评估集
EVALUATION_SET = [
    {
        "query": "高血压患者应该注意什么？",
        "expected_documents": ["doc_001", "doc_002"],
        "expected_answer_contains": ["低盐", "运动", "监测"],
    },
    # ...
]
```

## 12. 知识库检查清单

- [ ] 文档审核流程完整
- [ ] 分块策略合理
- [ ] 向量化服务正常
- [ ] 检索准确率达标
- [ ] 回答有引用来源
- [ ] 无答案时如实告知
- [ ] 不提供医疗诊断
- [ ] 降级策略生效
- [ ] 索引可重建
- [ ] 版本可追溯
- [ ] 隐私保护（本地处理）
- [ ] 性能达标

---

*知识库是健康助手的智慧源泉。可信、可追溯、可解释的 RAG，让健康回答有根有据。*
