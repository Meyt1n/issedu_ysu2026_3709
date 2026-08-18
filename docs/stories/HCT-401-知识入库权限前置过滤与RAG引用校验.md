# HCT-401：知识入库、权限前置过滤与 RAG 引用校验

## 任务元数据

- Issue：[#64](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/64)
- FR/NFR：FR-08、NFR-02、NFR-03
- 风险：R3
- 当前补充范围：本地批准清单入库、幂等重跑、可重建索引校验、无相关结果结构化降级
- 前置依赖：HCT-104、HCT-106、HCT-307

## 边界

知识来源必须记录来源、许可、版本、SHA-256、生效窗口、权限域和删除责任。检索先做身份/家庭/成员权限过滤，再进行本地检索；模型只能引用本轮工具返回的可访问文档片段。未经审核的网页、聊天内容、真实家庭健康资料和云端知识回退不属于本 Story。

## 验收条件

- [x] 知识文档自动分块并保存原文哈希、版本、许可、权限域和有效期。
- [x] 检索前过滤权限；未授权文档不进入候选、引用或助手上下文。
- [x] 引用必须匹配本轮返回的 `document_id/version/chunk_id`；伪造引用结构化降级。
- [x] 空查询、无授权文档、空索引、无相关结果、模型不可用和删除传播均有明确状态。
- [x] 本地批准清单可执行 dry-run；正式入库是原子操作且重复执行幂等。
- [x] 索引快照哈希内容和版本元数据，不依赖随机数据库 UUID，可用于重建一致性校验。

## 当前可运行入口

- `scripts/ingest_local_knowledge.py`：从批准 JSON 清单校验并入库，只接受清单指定的 UTF-8 `.md`/`.txt`。
- `docs/demo/本地RAG知识清单.json`：仅含合成演示知识卡。
- `docs/demo/本地RAG入库与运行.md`：dry-run、正式入库和 API 检索命令。

## 测试证据

- `tests/unit/test_hct401_knowledge.py`
- `tests/unit/test_local_knowledge_ingest.py`
- `tests/e2e/test_hct405_failure_degradation.py`
- `tests/e2e/test_hct405_deletion_propagation.py`

## 回滚

停止助手的知识检索调用，回退到结构化事实/规则卡；保留旧索引版本，删除或撤销异常文档并重新建立新版本快照。不得通过关闭权限过滤或改用云端健康上下文绕过故障。
