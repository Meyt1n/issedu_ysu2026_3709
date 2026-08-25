# HCT-450 助手回复智能度与编排优化 · 自评 Review（2026-08-25）

- 分支：`cursor/assistant-smarter-a666`；Story：[HCT-450](../stories/HCT-450-助手回复智能度与编排优化.md)；FR-08 / NFR-04 / NFR-07
- 背景：PR #426（症状用药放宽）与 PR #446 / HCT-448（空库友好降级）合并后，用户仍反馈「有回答时不聪明」。

## 根因定位（证据驱动）

1. **有卡却撞墙**（`src/api/app/local_agents.py::_synthesis_agent`）：检索命中后，模型若忘记把 `chunk_id` 抄进 `sources`，直接触发 `EVIDENCE_REQUIRED` 降级——真实证据被浪费成「缺少可核验的本地知识引用」。提示词只在证据 JSON 里埋着 chunk_id，从未点名要求引用。
2. **GENERAL 教学问用不上知识库**（`plan_agent_execution`）：GENERAL 直接跳过 knowledge 检索，23 张已审核教学卡对「居家照护习惯」类问题完全不可用。
3. **追问建议千篇一律**（`src/api/app/tool_call.py::suggest_follow_up_questions`）：只按关键字梯子选 3 条固定模板，不区分问题类型和是否命中知识，多为「这条回答依据了哪些…」式空话。
4. **分流说明工程腔**（`_classifier_explanation`）：默认输出「默认词表识别为「X」（模型分类默认关闭）」，用户不需要知道双通道术语。
5. **前端元信息堆叠**（`src/web/src/views/AssistantView.vue`）：问题类型 + 分流说明 + ⚠降级 + 越权红字 + ⚠风险提示 + 依据状态 + 逐条裸依据标识可同屏出现；`questionTypeLabel` 还缺 `SYMPTOM_MEDICATION`，症状问题被标成「一般健康信息」。
6. **回答结构无引导**：系统提示词未要求「先回应→片段要点→过敏史/就医提醒」，也未要求多轮承接，导致复读式、客服式回答。

## 落地改动

| 项 | 文件 | 内容 |
|---|---|---|
| A/F 回答结构与多轮承接 | `tool_call.py` | 系统提示词新增第 6/7 条：命中知识时先直接回应→2~4 条片段要点→一句过敏史/就医提醒；已有上一轮则承接不重复自我介绍 |
| B 引用点名+补正重试 | `local_agents.py` | synthesis 提示词逐条点名 `chunk_id｜资料名` 并要求原样填入 sources；漏引用时追加纠正 system 消息重试一次，仍失败按原逻辑降级 |
| G GENERAL 可选用知识 | `local_agents.py` | GENERAL 也跑本地检索（问候快路径不变、外搜仍跳过）；引用则绑 citations，未引用软通过不新增失败墙；伪造引用仍 `CITATION_NOT_FOUND` |
| D 差异化追问 | `tool_call.py` | `suggest_follow_up_questions` 新增 `query_type`/`has_citations`：症状+命中→过敏史/就医/查记录；症状+空库→就医时机/资料入库；GENERAL+命中→资料延伸；旧调用方不变 |
| E 分流与元信息瘦身 | `local_agents.py`、`AssistantView.vue`、新 `assistant/replyMeta.ts` | 默认分流说明改为「已按「X」处理这个问题」；前端合并类型+分流为一行、escalate 时去重 risk_notice、已展开引用卡不再重复列裸标识、confidence 中文化、补 `SYMPTOM_MEDICATION` 标签 |

未做 C（检索改写/同义词扩展）：金标 kb-gold-025/026 与 `test_local_knowledge_ingest.py` 已证明「夏天吹空调后有点鼻塞」能命中感冒卡，改检索性价比低、风险高，判定不动。

## 硬边界确认（不回退）

- `MEDICATION_SAFETY` 无本地证据：仍 `EVIDENCE_REQUIRED` + escalate（`test_medication_safety_short_circuits_without_knowledge` 全绿）。
- HCT-448 空库友好路径：仍 `KNOWLEDGE_UNAVAILABLE`、escalate=false（`test_symptom_medication_without_knowledge_gets_friendly_fallback` 全绿）。
- 引用校验未关闭：伪造引用仍拒绝；症状/用药安全命中却引用失败，在一次补正后仍如实降级（新增 `test_symptom_answer_still_walls_when_citation_missing_after_retry`）。
- 无新增默认开启的外网或模型分类开关；无迁移、无配置变更。

## 测试证据

- `uv run pytest`：新增 `tests/unit/test_hct450_assistant_smartness.py` 9 项全绿（含验收场景「感冒卡入库 + 引用回答 + 不升级」端到端）；受影响文件 `test_hct430_local_agents.py`（GENERAL 计划期望更新 1 处）、`test_hct430_ux_ops.py`、`test_hct411_follow_up_suggestions.py`、`test_hct403_tool_call.py`、`test_local_knowledge_ingest.py`、`test_hct442_question_classifier.py`、契约测试全绿。全仓 pytest 仅 `tests/deploy/test_hct408_deploy.py` 6 项失败——本 VM 无 docker，基线（未改动工作区）同样失败，与本次无关。
- `uv run ruff check`（触碰文件）通过。
- 前端：`replyMeta.test.ts` 8 项、`npm run test:web` 166 项、`npm run check:web`、`npm run build:web` 全部通过。
- 未运行真机 Ollama：模型行为用 scripted fixture 钉住（引用/漏引用/两次失败三种剧本），真机听感与 R3 验收仍需维护者按部署指南执行。

## 回滚

`git revert` 本 PR 提交即可整体回退；无数据迁移与配置依赖。

## 残留风险

- P1：补正重试最多多一次本机推理（仅在「命中知识但漏引用」时触发），弱设备延迟略增。
- P2：GENERAL 检索命中不相关卡时，提示词允许模型忽略（sources 留空），但小模型可能被无关片段带偏；如反馈变差可将 GENERAL 检索改为配置开关。
- P2：提示词对未微调模型的遵循度未做真机盲测；scripted 测试只保证编排与校验行为。
