# HomeCare Twin RAG

RAG 保存版本化药品说明书、公开权威资料、审核规则依据和经授权家庭文档。每份文档记录来源、许可、版本、哈希、权限域和失效时间；切片保留页码、章节或表格定位。

检索前执行家庭和成员级权限过滤，文档内指令只视为数据。返回结果必须携带真实 `document_id`、版本和 `chunk_id`，回答主张需通过引用忠实性检查；检索为空或引用不足时必须澄清或拒答。

向量索引是可重建派生物，不是事实主库。索引、Embedding、切片和知识版本必须绑定并可回滚。

## 检索端口

`ai.rag.retrieval` 提供稳定的 `Retriever` 协议、`RetrievalScope` 授权范围和
`ChunkHit` 引用结果。当前默认实现 `LocalKnowledgeRetriever` 适配本地
`app.knowledge.retrieve`，因此 API 与本地助手共享同一套权限过滤、版本字段和
降级语义。未来接入本地向量索引时，只需实现 `Retriever`，不改变调用方契约。
