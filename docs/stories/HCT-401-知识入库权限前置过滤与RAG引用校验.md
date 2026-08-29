# HCT-401：知识入库、权限前置过滤与 RAG 引用校验

## 任务元数据

- Issue：[#64](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/64)
- 2026-08-29 来源扩充 Issue：[#613](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/613)
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
- `docs/demo/本地RAG知识清单.json`：22 张合成教学演示知识卡（均含 FAQ；主题覆盖用药安全、存放处置、过敏授权、指标、紧急联络、包装复核、提醒升级、字段授权、事件追加、规则证据分区、本地隐私、拒答、时间窗预算、跌倒观察、外出备药、医嘱确认、删除撤权、天气行动卡、药箱盘点、语音边界、指标趋势、视觉门控）。
- `docs/demo/本地RAG检索金标集.json`：问句→应命中文档金标（含同义词用例与防串题约束）。
- `docs/demo/本地RAG入库与运行.md`：dry-run / 正式入库 / 同义词与轻量向量说明（索引版本 `demo-cn-en-v4`）。
- `docs/knowledge/approved/`：正式批准知识接入路径与脱敏说明书摘要样例（与 demo 分离）。
- `docs/knowledge/crawl/`：白名单爬虫、夹具与运营说明；`staging/` → `approved/incoming/` → dry-run 入库（禁止 auto_ingest）。

## 2026-08-25 增量（知识库扩充与检索质量修复）

- 修复检索评分：IDF 改为块级平滑计算（旧实现把文档数与块级 df 混用，多块文档中的常见词会得到负权重并被静默丢弃，触发 `NO_RELEVANT_RESULTS`）；词频改为次线性（1 + ln tf）并按查询词覆盖度加权，堆砌单一关键词的块不再压过真正覆盖问题的块。
- 分块改为 Markdown 章节感知：按标题切分（超长章节回退为带重叠的字符窗口），`locator` 携带 `section:<章节名>` 前缀，对齐 07-AI与RAG设计规范「保留章节标签」的要求。
- 空白/纯停用词查询在检索入口提前返回 `EMPTY_QUERY` 结构化降级。
- `local_agents._knowledge_agent` 的 trace 区分「检索完成但无命中」（`NO_RELEVANT_RESULTS`，`completed`）与真实阻断（`NO_AUTHORISED_DOCUMENTS`/`EMPTY_INDEX`/越权，`blocked`）；权限前置过滤、引用校验与用药安全短路逻辑均未弱化。
- 知识库扩充为 22 份合成教学卡；清单逐项登记 source/license/version/permission_scope/content_sha256。
- **深度：** 每张卡补充 FAQ 式问答块（仍禁剂量/诊断/导流），文档版本统一推进到 `demo-cn-en-v4`。
- **检索：** 本地同义词/别名扩展（`knowledge_synonyms.py`）+ 词袋余弦轻量向量混入 TF-IDF；无云端 embedding。
- **评测：** `本地RAG检索金标集.json` + `test_hct401_knowledge_gold.py` 固定 top-1 命中与防串题。
- **正式知识：** `docs/knowledge/approved/` 提供脱敏说明书摘要接入路径与 example 清单，禁止 PDF 直接进入 `docs/demo`。
- **持续更新：** 白名单爬虫按 `refresh_hours` 到期刷新 → staging 审核/拒绝 → 晋升 → dry-run 入库；API/Web/CI 默认仅夹具，远程需 CLI `--live`；`tests/unit/test_knowledge_crawl.py`。

## 2026-08-25 增量（爬虫运营可发现性与权限引导）

针对「用户不知道知识爬虫如何启用」的反馈补齐运营闭环，安全默认不变（API 强制离线夹具、永不 auto_ingest）：

- **权限引导**：非 steward 访问 `/api/v1/knowledge/crawl/*` 仍返回 403 `KNOWLEDGE_STEWARD_REQUIRED`，但 Web 知识页现在显示明确的「需要知识管理员身份」引导（切换 `demo-parent`/`knowledge-steward`/`demo-*`，或配置 `KNOWLEDGE_ADMIN_ACTORS`），不再静默显示空列表；steward 判定新增 `.env` 的 `KNOWLEDGE_ADMIN_ACTORS` 名单（`src/api/app/routes.py::_require_knowledge_steward`）。
- **一键教学闭环**：知识页新增「一键教学闭环：抓取 → 批准 → 晋升」按钮（仅处理本地夹具草稿），完成后展示可复制的 `ingest_local_knowledge.py --dry-run` 命令；正式入库仍须人工执行 dry-run。
- **文档**：crawl README 新增「谁可以操作」权限表；本地部署指南新增 §4.3「如何刷新知识库」；README 新增快速短节。
- 对应测试：`tests/unit/test_knowledge_crawl.py`（403 原因契约、`KNOWLEDGE_ADMIN_ACTORS` 放行）、`src/web/src/knowledge/crawlPanel.test.ts`（403 → 引导、待批草稿筛选、闭环摘要文案）。

## 2026-08-25 增量（爬虫失败原因区分与 Compose 部署修复）

针对「知识页所有卡片一律显示 API 不可用 / 暂时不可用」的反馈修复两层根因，安全默认不变（API 强制离线夹具、永不 auto_ingest）：

- **Compose 部署缺配置（后端根因）**：`docker/api.Dockerfile` 此前不拷贝 `docs/knowledge/`，容器内 `knowledge_crawl.py` 的 allowlist/夹具路径（`/app/docs/knowledge/crawl/...`）不存在，`/knowledge/crawl/status|run` 以裸 500 失败。现镜像携带 `docs/knowledge/`，且这两个端点把 `FileNotFoundError` 译为结构化 503 `KNOWLEDGE_CRAWL_CONFIG_MISSING`（`routes.py::_crawl_config_missing_error`），旧镜像也能给出「重建镜像」指引而不是含糊文案。
- **前端错误合并（前端根因）**：`api/client.ts` 此前把「连接失败」与「15 秒超时」都归为 `DEPENDENCY_UNAVAILABLE`，`formatError` 一律译成「本地 API 服务不可用」。现超时独立为 `REQUEST_TIMEOUT`；`formatError` 对连接失败给出启动/端口//health 排查指引，对 403 `KNOWLEDGE_STEWARD_REQUIRED` 给出知识管理员指引（绝不再说成 API 不可用），对 503 `KNOWLEDGE_CRAWL_CONFIG_MISSING`、501 `REAL_AUTH_REQUIRED` 与其余 5xx 均展示真实原因。
- **知识页文案**：爬虫面板、「联网搜索运行状态」卡与「在用文档」卡在读取失败时展示上述真实原因；「知识库读取失败」与「知识库还是空的」明确区分，staging 读取失败时不再显示「暂无 staging 草稿」。
- 对应测试：`tests/unit/test_knowledge_crawl.py::test_knowledge_crawl_config_missing_is_structured_503`、`src/web/src/api/client.test.ts`（超时 → `REQUEST_TIMEOUT`、连接失败 → `DEPENDENCY_UNAVAILABLE`）、`src/web/src/store.test.ts`（`formatError` 六类原因映射）、`src/web/src/knowledge/crawlPanel.test.ts`（network/timeout/config-missing/forbidden 分类）。
- 文档：[联网搜索与知识库刷新启用指南](../demo/联网搜索与知识库刷新启用指南.md) 排障表补「无法连接本地 API / 响应超时 / 需要知识管理员 / 爬虫配置缺失」四行。
- 回滚：还原 `docker/api.Dockerfile` 的 COPY 行与本次前端/路由提交即可；不涉及数据迁移。

## 2026-08-26 增量（爬虫/知识库实用化：详情查看与变更演示）

针对「资料点不开看不到正文、全量抓取永远是同一批未变更夹具」的用户反馈补齐产品可用性，安全默认不变（API 强制离线夹具、staging ≠ 正式证据、永不 auto_ingest）：

- **可点击查看详情**：
  - `GET /knowledge/documents/{id}` 升级为详情契约（`KnowledgeDocumentDetailRead`）：在列表字段之外返回 `content` 正文、`chunk_count` 与检索分块预览；权限过滤与列表一致，越权仍返回同样的 404（不泄露存在性）。「在用文档」列表点标题或「查看详情」打开只读模态，不影响登记/下线。
  - 新增 `GET /knowledge/crawl/staging/{source_id}`（steward 权限）：返回抓取正文 Markdown、来源 URL、SHA-256、状态、fetched_at、审核备注与批准/拒绝轨迹，响应固定携带 `is_formal_evidence: false` 与免责声明；source_id 做白名单校验防路径穿越。Web 端草稿标题/「查看」按钮打开详情。
- **变更可见**：抓取 meta 新增 `first_fetch`，报告新增 `new_sources`；Web 报告与草稿徽标区分「新来源 / 有更新 / 未变更」，全部未变更时明确解释“内容哈希未变属正常”并指向教学演示路径；内容变化仍重置为 draft 待重新审核。
- **模拟来源更新（教学演示）**：新增 `POST /knowledge/crawl/simulate-update`（steward 权限，`?reset=true` 可清除）。仅对 `fixture://` 来源写入 gitignore 的 `docs/knowledge/staging/fixture_overrides/` 运行时 overlay（仓库夹具不被修改），追加清晰标注的「教学演示模拟更新 vN」段落；下一次抓取显示「有更新」并重置 draft。meta/status 详情携带 `demo_override` 透明标记；不出网、仍进 staging、永不 auto_ingest。
- **来源可解释**：`crawl status` 的 sources 增补 `demo_override`；Web 端新增只读「白名单来源」折叠列表（夹具/远程、启用状态、refresh_hours、到期、上次抓取），并展示添加真实 HTTPS 源 + CLI `--live` 的说明与可复制命令，回答“为什么总是这几个”。
- **可演示来源扩充**：新增 2 个合成教学夹具 `seasonal-home-care.html`（换季与流感季居家照护）与 `med-disposal.html`（过期药品清理与回收），登记进 allowlist（白名单 7 源，其中夹具 6）；夹具头部带 `fixture-version` 注释供开发者演示变更。
- **部署**：新增仓库 `.dockerignore`，确保 API 镜像 `COPY docs/knowledge` 时排除 staging/approved 运行产物与教学 overlay。
- 文档：crawl README（详情查看、为何未变更、三条“看到更新”路径、白名单面板）、启用指南（详情/模拟更新/排障行）。

## 测试证据

### 2026-08-29 权威来源与 100 条本地知识验收增量

- 受控知识抓取白名单扩展为 27 个 HTTPS 官方主机，来源清单扩展为 27 条（6 个离线夹具、21 个远程来源登记）；新增远程来源均保持 `enabled: false`，只有管理员显式启用并使用 CLI `--live` 才可进入 staging，`auto_ingest=false` 和人工审核门禁未改变。
- 来源覆盖国家卫生健康委、中国疾控、WHO、CDC、FDA、DailyMed、NIA、NIDDK、NHLBI、AHRQ 等官方站点；每条登记摘要许可、刷新周期、主题和医疗安全备注，不复制整页内容。
- 本机 `demo-parent` 运行时批准批次新增 100 个独立中文摘要文档；正式索引 `approved-web-100-20260829-v1` 共 108 文档、532 分块，重复 dry-run 为 100 `skip` / 0 `create`。非授权账号可见 0 文档并返回 `NO_AUTHORISED_DOCUMENTS`。
- 10 组主题检索（用药、血压、糖尿病、跌倒、呼吸道、饮食、睡眠、心理、应急、最小必要共享）全部命中；真实搜索出口返回卫健委/中国政府官方结果，未知域名与 HTTP 继续被阻断。
- 验收记录：[HCT-401 权威健康知识与白名单扩充验收](../reviews/HCT-401-权威健康知识与白名单扩充验收-20260829.md)。

- `tests/unit/test_knowledge_crawl.py`：staging 详情（正文/标志/404/穿越 id）、模拟更新（changed→draft、demo_override、二次 bump 递增、reset 恢复、仓库夹具零改动）、新夹具登记、详情与模拟更新 API 契约（steward 403、404、reset）
- `tests/unit/test_hct401_knowledge.py::TestDocumentDetailApi`：详情返回正文+分块、越权 404 不泄露
- `src/web/src/knowledge/crawlPanel.test.ts`：新来源/有更新/未变更徽标、抓取摘要（全未变更解释 + 失败计数）、模拟更新摘要
- `tests/unit/test_hct401_knowledge.py`（含 IDF 负权重回归、覆盖度排序、章节分块定位三项新增用例）
- `tests/unit/test_local_knowledge_ingest.py`（含仓库清单入库与主题检索断言）
- `tests/unit/test_hct401_knowledge_gold.py`（金标集、同义词扩展、正式知识 example 哈希）
- `tests/unit/test_knowledge_crawl.py`（白名单抓取、到期刷新、域名闸门、审核拒绝、晋升、403 原因契约、管理员名单放行）
- `tests/unit/test_hct430_local_agents.py`（知识 agent 无命中/越权 trace 状态）
- `tests/e2e/test_hct405_failure_degradation.py`
- `tests/e2e/test_hct405_deletion_propagation.py`

## 回滚

停止助手的知识检索调用，回退到结构化事实/规则卡；保留旧索引版本，删除或撤销异常文档并重新建立新版本快照。不得通过关闭权限过滤或改用云端健康上下文绕过故障。
