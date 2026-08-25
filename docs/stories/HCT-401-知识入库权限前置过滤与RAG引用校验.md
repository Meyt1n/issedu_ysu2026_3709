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
- `docs/demo/本地RAG知识清单.json`：22 张合成教学演示知识卡（用药安全、存放处置、过敏授权、指标记录、紧急联络、包装复核，以及提醒升级、字段授权、事件追加、规则证据分区、本地隐私、拒答升级、时间窗预算、跌倒观察、外出备药、医嘱确认、删除撤权、天气行动卡、药箱盘点、语音边界、指标趋势、视觉门控等）。
- `docs/demo/本地RAG入库与运行.md`：dry-run、正式入库和 API 检索命令（当前索引版本 `demo-cn-en-v3`）。

## 2026-08-25 增量（知识库扩充与检索质量修复）

- 修复检索评分：IDF 改为块级平滑计算（旧实现把文档数与块级 df 混用，多块文档中的常见词会得到负权重并被静默丢弃，触发 `NO_RELEVANT_RESULTS`）；词频改为次线性（1 + ln tf）并按查询词覆盖度加权，堆砌单一关键词的块不再压过真正覆盖问题的块。
- 分块改为 Markdown 章节感知：按标题切分（超长章节回退为带重叠的字符窗口），`locator` 携带 `section:<章节名>` 前缀，对齐 07-AI与RAG设计规范「保留章节标签」的要求。
- 空白/纯停用词查询在检索入口提前返回 `EMPTY_QUERY` 结构化降级。
- `local_agents._knowledge_agent` 的 trace 区分「检索完成但无命中」（`NO_RELEVANT_RESULTS`，`completed`）与真实阻断（`NO_AUTHORISED_DOCUMENTS`/`EMPTY_INDEX`/越权，`blocked`）；权限前置过滤、引用校验与用药安全短路逻辑均未弱化。
- 知识库从 1 份扩充到 22 份合成教学卡（含 v2/v3 增量），清单逐项登记 source/license/version/permission_scope/content_sha256；`tests/unit/test_local_knowledge_ingest.py::test_repo_demo_manifest_ingests_and_topics_are_retrievable` 固定清单可入库、哈希一致且各主题查询各自命中对应文档。

## 测试证据

- `tests/unit/test_hct401_knowledge.py`（含 IDF 负权重回归、覆盖度排序、章节分块定位三项新增用例）
- `tests/unit/test_local_knowledge_ingest.py`（含仓库清单入库与主题检索断言）
- `tests/unit/test_hct430_local_agents.py`（知识 agent 无命中/越权 trace 状态）
- `tests/e2e/test_hct405_failure_degradation.py`
- `tests/e2e/test_hct405_deletion_propagation.py`

## 回滚

停止助手的知识检索调用，回退到结构化事实/规则卡；保留旧索引版本，删除或撤销异常文档并重新建立新版本快照。不得通过关闭权限过滤或改用云端健康上下文绕过故障。
