# HCT-443：RAG 检索接口抽象与可替换实现

- FR/NFR：FR-08、NFR-02（本地优先）、NFR-04
- 用户价值：检索实现可从 TF-IDF 平滑升级到向量检索，而不撕裂权限前置过滤与 citation 契约
- 范围：抽出 `retrieve(query, scope) -> ChunkHit[]` 端口；现有 `knowledge.py` TF-IDF 作为默认适配器；后续 FAISS/Qdrant 另开增量
- 非目标：本 Story 不引入云端向量服务、不提交真实健康语料、不宣称正式模型发布
- 风险：P2（架构）
- 依赖：HCT-401 权限前置过滤与引用校验保持不变
- 允许修改：`src/api/app/knowledge.py`、`src/ai/rag/`、助手工具绑定、契约/单元测试、本 Story、需求追踪矩阵
- 验收：Given 同一权限 scope，When 切换适配器，Then 返回 chunk_id/document_id/version 契约不变；越权文档仍不可见；缺证据仍结构化降级
- 回滚：配置回切 TF-IDF 适配器
- 状态：已批准待办（结构性重构，单独排期；本增量仅完成词表/n-gram 召回增强，不换向量引擎）
