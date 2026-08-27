# Story 卡片集：HCT-5xx 与 NEXT（2026-08-27）

> 状态：规划草案。编号为占位号，正式编号/Issue 号以维护者创建时为准；每张卡片被采纳后需在 `docs/stories/` 建立正式 Story 文件（含负责人、复核人、允许修改范围、回滚）才能进入 Ready。
> 通用非目标（所有卡片默认继承，不再逐卡重复）：不做诊断/处方/停药/换药/剂量判断；不做买药/问诊/广告导流；健康数据默认不出网；人脸非生产级生物识别；不放松 fail-closed 门禁。
> 波次与依赖见[下一期迭代规划](下一期迭代规划-2026-08-27.md) §4。

---

## Wave 0 治理与收口

### HCT-501 需求追踪矩阵与 Story 状态回填（治理收口）

- **FR/NFR**：NFR-03、NFR-06　**风险**：R1　**执行主体**：维护者（agent 无 issues 权限，仅供清单）
- **用户价值**：矩阵是唯一进度入口；滞后行会让后续排期与验收判断失真。
- **范围**：按[建议的矩阵与Issue回填清单](建议的矩阵与Issue回填清单.md)逐项修正矩阵行、补建缺失 Issue 并回填链接、裁决 HCT-452 撞号与 ADR-0006 重号。
- **非目标**：不重写历史行的既有证据描述；不改 Story 正文；不合并任何功能代码。
- **GWT**：
  - Given 回填清单中的每一项，When 维护者执行或书面拒绝，Then 清单项全部有处理结论；
  - Given HCT-428 行，When 回填完成，Then 状态与 PR #371 合并事实一致且链接可点；
  - Given 矩阵「待开 Issue」行，When Issue 建立，Then 行内出现真实 Issue 链接。
- **技术方案**：纯文档变更，单独 PR；按矩阵更新门禁（状态变更必须带证据链接）执行。
- **可粘贴 Issue 正文**：

```markdown
标题：[HCT-501] 需求追踪矩阵与 Story 状态回填（治理收口）
- Story：HCT-501（待建 docs/stories/HCT-501-矩阵与Story状态回填.md）
- FR/NFR：NFR-03、NFR-06　风险：R1　建议标签：area:test, priority:P0
任务：按 docs/planning/建议的矩阵与Issue回填清单.md 逐项处理：
1. 修正滞后行（HCT-428 已由 PR #371 于 2026-08-24 合并等，见清单 §1）；
2. 为清单 §2 所列 Story 补建 Issue 并回填矩阵链接；
3. 裁决 HCT-452 撞号与 docs/decisions 两个 0006 重号。
验收：清单每项有「已执行/拒绝+理由」结论；矩阵变更 PR 合并。
回滚：revert 矩阵变更 commit。
```

### HCT-502 HCT-458 告警审计元数据收口（评审合并 #481）

- **FR/NFR**：FR-05、NFR-03、NFR-07　**风险**：R2　**依赖**：PR [#481](https://github.com/Meyt1n/issedu_ysu2026_3709/pull/481)
- **用户价值**：合并后风险告警的去重键/合并数/预算结论/下次可见时间全部可解释，解锁 MOB-156 移动端真实呈现。
- **范围**：评审并合并 #481；合并后更新矩阵 HCT-458 相关行；通知 MOB-156 补真实后端截图。
- **非目标**：不在该 PR 上追加新功能；不改预算规则本身。
- **GWT**：
  - Given #481 的 diff 与测试证据，When 维护者按 PR 门禁核对（任务/测试/风险/回滚），Then 合并或给出必改项；
  - Given 合并完成，When 查询 `GET /members/{id}/risks`，Then 响应含 `deduplication_key`/`merged_count`/`budget_status`/`next_visible_at` 且不含健康正文；
  - Given MOB-156，When 连接真实后端，Then 移动端能展示上述元数据并对缺失字段安全降级。
- **技术方案**：无新增开发；评审要点为「证据摘要只返回来源事件数量、不泄露正文」与预算重置时间的 UTC 语义（与 HCT-459 一致）。
- **可粘贴 Issue 正文**：

```markdown
标题：[HCT-502] 收口 HCT-458：评审合并 PR #481 并联动 MOB-156
- Story：HCT-458（已有 docs/stories/HCT-457-风险告警合并与预算元数据.md 的后续切片；如需独立文件由维护者裁决）
- FR/NFR：FR-05、NFR-03、NFR-07　风险：R2　建议标签：area:backend, priority:P0
任务：1) 按合并门禁评审 PR #481（Closes #480）；2) 合并后回填矩阵；3) MOB-156（#245）补真实后端截图。
验收：#481 合并；风险接口审计字段契约测试在 master 全绿；MOB-156 证据更新。
回滚：revert #481 合并 commit（无迁移）。
```

---

## Wave 1 P0 证据闭环

### HCT-503 HCT-408 Compose 实跑备份恢复演练与三档部署 R3

- **FR/NFR**：NFR-02、NFR-04、NFR-06　**风险**：R3　**依赖**：有 Docker 的执行机（当前 agent 环境无 Docker，矩阵已记录）
- **用户价值**：教学库可被安全清空/恢复是部署硬承诺；没有实跑演练，「三档部署」不能宣称已验收。
- **范围**：在真实 Docker 环境实跑 `basic/enhanced/dev` 三档 `up --wait`；执行 MySQL 备份→DROP→IMPORT→校验全链演练；产出演练记录与 JSON 证据；完成独立 R3 复核。
- **非目标**：不改备份脚本功能面（除非演练暴露缺陷）；不做云端备份。
- **GWT**：
  - Given 干净 Docker 环境，When 依次 `up` 三档，Then 全部健康检查通过并有记录；
  - Given 含教学数据的 MySQL，When 备份→DROP DATABASE→IMPORT，Then 事件数/投影一致性校验通过；
  - Given 演练记录，When 独立复核人核对，Then R3 结论与限制写入 `docs/reviews/`。
- **技术方案**：复用 `scripts/backup.sh`/`restore.sh`、`scripts/hct408_disposable_restore_drill.py`、`tests/deploy/test_hct408_deploy.py`；证据落 `docs/reviews/HCT-408-*`（新文件）。
- **可粘贴 Issue 正文**：

```markdown
标题：[HCT-503] HCT-408 收口：Compose 实跑 MySQL 备份恢复演练与三档部署 R3
- Story：HCT-408（docs/stories/HCT-408-三档部署备份恢复与回滚.md）　Related to #71
- FR/NFR：NFR-02、NFR-04、NFR-06　风险：R3　建议标签：area:devops, priority:P0
任务：真实 Docker 环境三档 up --wait；MySQL 备份→DROP→IMPORT 实跑；演练记录 + JSON 证据；独立 R3。
验收：演练记录合并进 docs/reviews/；矩阵 HCT-408 行更新；失败场景（备份缺失/导入中断）至少各演练一次。
回滚：演练本身可弃置环境执行，不影响 master；文档 revert 即回滚。
```

### HCT-504 HCT-402 QLoRA 真实训练、盲测对照与模型卡

- **FR/NFR**：FR-08、NFR-05、NFR-06　**风险**：R3　**依赖**：研发机 GPU；已批准数据集 `hct402-instruction-approved-v1`
- **用户价值**：v5 微调输出目前只能标「教学演示」；没有 base/QLoRA 同盲测集对照，FR-08 的模型证据永远缺一角。
- **范围**：在研发机完成真实 QLoRA 训练；用同一盲测集跑 base vs QLoRA 对照与安全评估；发布模型卡、登记哈希与回滚版本。权重不进 Git。
- **非目标**：不追求指标 SOTA；不做云端训练/推理；不把未过安全评估的模型接入默认配置。
- **GWT**：
  - Given 批准数据集与冻结盲测集，When 训练与评估完成，Then 产出双列对照报告（含失败样例）且可复现（种子/配置/哈希齐全）；
  - Given 安全评估，When 医疗拒答/越权/导流样例回归，Then 无新增违规输出；
  - Given 模型卡与登记，When 维护者复核，Then 发布或回滚决定有记录。
- **技术方案**：复用 `scripts/hct402_evaluate_blind.py` 与数据卡 V1.1 批准范围；模型卡落 `docs/model-cards/`（新文件）；登记进 model-registry。
- **可粘贴 Issue 正文**：

```markdown
标题：[HCT-504] HCT-402 收口：QLoRA 真实训练、base/QLoRA 盲测对照与模型卡
- Story：HCT-402（docs/stories/HCT-402-指令数据与QLoRA盲测对照.md）　Related to #65
- FR/NFR：FR-08、NFR-05、NFR-06　风险：R3　建议标签：area:ai, priority:P0
任务：研发机真实 QLoRA 训练（hct402-instruction-approved-v1）；同盲测集 base/QLoRA 对照 + 安全评估；模型卡/哈希/回滚登记。
验收：对照报告与模型卡合并；scripts/hct402_evaluate_blind.py 结果可复现；权重不入库。
回滚：模型登记标记回滚版本；配置回指 base 模型。
```

### HCT-505 人脸阈值现场标定与教学演示级验收

- **FR/NFR**：FR-01、NFR-01、NFR-05　**风险**：R3　**依赖**：真实摄像头/演示机（云端不能代采真人脸）
- **用户价值**：默认阈值来自公开样例；不标定就无法承诺课堂演示的识别通过率与误识边界。
- **范围**：在目标演示机用 `scripts/calibrate_face_thresholds.py` 按家庭摄像头标定；记录失败桶分布与推荐阈值；完成教学演示级 R3（明确标注非生产级生物识别）。
- **非目标**：不宣称生产级识别率；不收集/提交任何真人脸图像到仓库；不接云端人脸服务。
- **GWT**：
  - Given 演示机与授权参与者，When 标定脚本运行，Then 输出阈值建议与 ROC 摘要（仅统计量，无生物特征载荷）；
  - Given 标定后配置，When 参与者按操作手册刷脸登录，Then 通过率与失败桶分布满足演示预期并有记录；
  - Given R3 复核，When 结论落 `docs/reviews/`，Then 明确「教学演示级」限制与回滚（还原默认阈值）方式。
- **技术方案**：复用 HCT-424/425 现有管线与 `docs/demo/人脸凭证录入与登录操作手册.md`；记录只含统计量与配置值。
- **可粘贴 Issue 正文**：

```markdown
标题：[HCT-505] 人脸阈值现场标定与教学演示级验收（HCT-425 收口件）
- Story：HCT-425（docs/stories/HCT-425-人脸识别登录与活体检测.md）　Related to #281、#280
- FR/NFR：FR-01、NFR-01、NFR-05　风险：R3　建议标签：area:vision, area:security, priority:P0
任务：演示机 calibrate_face_thresholds.py 标定；失败桶分布记录；教学演示级 R3；不提交任何人脸数据。
验收：标定记录（仅统计量）合并 docs/reviews/；.env 阈值项有推荐值与回滚默认值；矩阵 HCT-425 行更新。
回滚：还原默认阈值配置。
```

### HCT-506 HCT-405 真实链路连续演示与最终验收门禁（W1 收口件）

- **FR/NFR**：FR-01 至 FR-10　**风险**：R3　**依赖**：HCT-503/504/505 产出；HCT-203 维护者 waiver 现状
- **用户价值**：P0 的最终承诺是「连续演示双闭环」；当前只有合成路径自动化，没有一次真实链路的完整走通。
- **范围**：按 `docs/demo/HCT424-HCT425-HCT405-连续展示主线.md` 完整跑一遍真实链路（真实人脸登录→扫药盒→复核入档→规则→助手解释→计划确认），录屏归档；跑 `scripts/hct405_acceptance_gate.py` 并保留输出；跨组 R3。
- **非目标**：不为演示顺利而绕过质量门控/复核/授权（拒识与降级本身是演示内容）；正式药品固定集缺口如仍未解锁（NEXT-03），按 DEMO_ONLY 如实标注而非伪装。
- **GWT**：
  - Given W1 前三项产出就位，When 连续演示执行，Then 主链 10 步各有时间戳记录且失败步骤如实标注；
  - Given 演示录屏与门禁输出，When 跨组复核，Then 结论与未关闭缺口清单写入矩阵；
  - Given 演示中出现拒识/降级，When 记录，Then 作为正面证据（拒识可解释）而非缺陷。
- **技术方案**：无新增功能开发；主要是环境编排（路径 C 全功能栈）+ 证据归档（`docs/reviews/` 新文件 + 录屏在交付包索引登记）。
- **可粘贴 Issue 正文**：

```markdown
标题：[HCT-506] HCT-405 真实链路连续演示与最终验收门禁（依赖 HCT-503/504/505）
- Story：HCT-405（docs/stories/HCT-405-core-e2e.md）　Related to #70、#73
- FR/NFR：FR-01 至 FR-10　风险：R3　建议标签：area:test, priority:P0
任务：路径 C 全功能栈连续演示（真实人脸/真实模型/实跑部署）；hct405_acceptance_gate 输出归档；录屏；跨组 R3。
验收：演示记录 + 门禁输出合并；未关闭缺口在矩阵如实标注；不得用合成夹具冒充真实链路。
回滚：纯验收活动，无代码回滚面。
```

---

## Wave 2 助手与隐私成熟度

### HCT-507 ADR-0007 残留收口：member 级出网隐私 R3 与导流过滤 badcase 回归池

- **FR/NFR**：FR-08、NFR-01、NFR-02　**风险**：R3　**依赖**：ADR-0007（已合并）
- **用户价值**：#496 自留了两条残留风险：`network_context_level=member` 需要隐私 R3 才能在真实部署启用；promo/句级清洗正则需要持续 badcase 维护，否则会静默腐化。
- **范围**：(a) 对 member 级出网做脱敏审查（哪些字段出网、脱敏是否充分、审计是否可追溯），产出 R3 结论与启用前置条件；(b) 建立导流过滤/句级清洗的固定 badcase 集与回归测试，纳入常规 pytest。
- **非目标**：不默认开启 member 级；不放宽 `DOSE_DECISION` 硬拒；不引入新出网渠道。
- **GWT**：
  - Given member 级请求样例，When 审查脱敏与审计链，Then R3 结论明确「可启用条件/禁用条件」并落 `docs/reviews/`；
  - Given badcase 固定集，When 回归运行，Then 导流/剂量句拦截无回退；新 badcase 有登记入口；
  - Given 生产配置，When 未过 R3，Then member 级保持不可启用（fail-closed）。
- **技术方案**：审查对象为 `src/api/app/local_agents.py`/`egress_guard.py`/`search_providers.py` 的脱敏与白名单路径；badcase 集放 `tests/safety/`（扩展 `test_hct430_open_egress.py` 家族）。
- **可粘贴 Issue 正文**：

```markdown
标题：[HCT-507] ADR-0007 残留收口：member 级出网隐私 R3 + 导流过滤 badcase 回归池
- Story：待建 docs/stories/HCT-507-*.md（承接 HCT-430，Related to #310）
- FR/NFR：FR-08、NFR-01、NFR-02　风险：R3　建议标签：area:security, area:ai, priority:P0
任务：member 级出网脱敏审查与 R3；badcase 固定集 + 回归测试入库；启用条件写入隐私规范引用处（新文档，不改旧文）。
验收：R3 记录合并；tests/safety 新增回归全绿；member 级默认关闭不变。
回滚：revert 测试与文档 commit；运行时配置保持 query_only。
```

### HCT-508 助手真实 Ollama 联调证据补跑

- **FR/NFR**：FR-08、NFR-04　**风险**：R2　**依赖**：本机 Ollama + 已登记模型（可复用 HCT-504 产出，非硬依赖）
- **用户价值**：#496 的验收明确记录「Ollama live sample 未跑（agent 环境不可用）」；统一安全策略的真实生成路径需要一次实机冒烟补证。
- **范围**：在有 Ollama 的机器按 `docs/demo/local-llm-v5.md` 起全栈，覆盖：正常生成、无证据软化路径（带风险提示）、`DOSE_DECISION` 硬拒、联网 opt-in 真实搜索、Ollama 断连降级五类样例；冒烟记录归档。
- **非目标**：不做性能压测；不改安全策略代码（发现缺陷另立 Issue）。
- **GWT**：
  - Given 全功能栈，When 五类样例逐一执行，Then 每类有请求/响应摘要（脱敏）与结论；
  - Given Ollama 停止，When 提问，Then 结构化降级且页面提示准确；
  - Given 冒烟记录，When 归档 `docs/reviews/`，Then 矩阵 FR-08 证据链接更新。
- **技术方案**：类比既有 `docs/reviews/HCT-430-助手演示冒烟记录.md` 的记录格式新增一篇。
- **可粘贴 Issue 正文**：

```markdown
标题：[HCT-508] 助手统一安全策略真实 Ollama 联调冒烟补证（#496 遗留）
- Story：待建 docs/stories/HCT-508-*.md（承接 HCT-403/430/451）
- FR/NFR：FR-08、NFR-04　风险：R2　建议标签：area:ai, priority:P1
任务：实机五类样例冒烟（正常/软化/硬拒/联网/断连），脱敏记录归档 docs/reviews/。
验收：冒烟记录合并；发现的缺陷各自另立 Issue，不在本任务修。
回滚：纯验收活动，无代码回滚面。
```

---

## Wave 3 移动端与演示打磨（依赖真机）

### NEXT-M1 MOB-148 发布 Gate 阻塞项集中收口

- **FR/NFR**：FR-01 至 FR-07、NFR-01 至 NFR-07　**风险**：R3　**依赖**：Android 真机、受控发布环境
- **摘要**：按 `APP/docs/移动端发布阻塞项与接管清单.md` 集中处理 APK 构建、受控后端联调、真机无障碍/语音矩阵与回滚签收；PR #497/#498 已解锁性能与证据文档，剩余项全部需要设备持有人执行。真机矩阵**不得由 Cloud Agent 代签**。
- **Issue 正文要点**：`标题：[NEXT-M1] MOB-148 发布 Gate 阻塞项集中收口　Related to #234；验收 = APP/docs/移动端发布门禁证据索引.md 全绿或逐项豁免记录`。

### NEXT-M2 语音与播报真机验收

- **FR/NFR**：FR-08、NFR-02、NFR-07　**风险**：R2　**依赖**：Android 真机、Natural 类中文 TTS 语音包
- **摘要**：HCT-412（PR #490）与 MOB-150 的语音成熟度增量已合并，欠隐私 R3 与真机矩阵（`docs/testing/MOB-150-Android真机语音助手验收记录.md` 待设备签收）；含听感准备（`docs/demo/中文语音包与听感准备说明.md`）。
- **Issue 正文要点**：`标题：[NEXT-M2] HCT-412/MOB-150 语音真机验收与隐私 R3　Related to #210、#176；验收 = 真机矩阵签收 + R3 记录`。

---

## NEXT 未排期候选（进入池，待下下期裁决）

| 占位号 | 摘要 | 关键依赖 | 建 Issue 时的要点 |
|---|---|---|---|
| NEXT-01 | 知识库运营常态化：白名单源扩充、staging 审核节奏、金标集维护、`--live` 抓取值守 | 知识管理员人力 | 承接 HCT-401；永不 auto_ingest 不变 |
| NEXT-02 | 正式部署认证收口：CSRF 防护、密钥/签名轮换演练、`ALLOW_DEV_ACTOR_HEADER` 关闭下的全链回归 | HCT-417/427/428 既有实现 | 矩阵已把「轮换/CSRF」列为正式部署阻断项 |
| NEXT-03 | HCT-201 正式药品固定集授权采集：正式授权、真实分组、conflict 双证据、删除传播，解锁 HCT-404/FR-10 | **外部：数据许可**；项目负责人裁决 | 未解锁前 `hct201-formal-drug-set` 保持恒不可用 |
