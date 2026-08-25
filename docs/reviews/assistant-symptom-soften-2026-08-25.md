# 症状用药空库友好降级（HCT-448，延续方案 A，2026-08-25）

- **分支**：`cursor/assistant-symptom-soften-a666`
- **口径**：修「过严拦截/过早降级」，不拆医疗硬边界；`MEDICATION_SAFETY` 无证据仍硬降级
- **绑定**：FR-08、NFR-04、NFR-07；Story [HCT-448](../stories/HCT-448-症状用药空库友好降级.md)

## 根因

1. 空库/无授权文档时 `retrieve` 抛 `NO_AUTHORISED_DOCUMENTS`，knowledge agent trace 记 `blocked`，前端显示「本地资料检索 · 已拦截」——把检索缺口伪装成风控拦截；
2. `_medication_safety_short_circuit` 对 `SYMPTOM_MEDICATION` 与 `MEDICATION_SAFETY` 同样返回 `EVIDENCE_REQUIRED + escalate=true`，前端叠加「缺少可核验引用」「超出系统边界」「受控回复」三连；
3. 单 agent 路径 `run_assistant` 中 `SYMPTOM_MEDICATION` 无引用同样落入严厉 `EVIDENCE_REQUIRED`；
4. 演示知识库 22 卡无感冒/鼻塞类照护卡，该类问题必然无命中。

## 变更

1. `SYMPTOM_MEDICATION` 无知识命中 → 新降级 `KNOWLEDGE_UNAVAILABLE`：确定性回答（`seasonal_care_hint` 季节照护 + 明确本机暂无已审核知识卡 + 建议咨询医生药师），`escalate=false`，保留追问建议；单/多 agent 一致；模型无证据草稿一律丢弃，不「加免责声明放开乱答」
2. knowledge agent trace：`NO_AUTHORISED_DOCUMENTS`/`EMPTY_INDEX` → `degraded`（「本机暂无当前可用的已审核知识卡」）；`EMPTY_QUERY` → completed-empty；`blocked` 仅留给真实工具/范围失败
3. `AssistantView.vue`：`KNOWLEDGE_UNAVAILABLE` 显示友好提示（非警示三连）
4. 新增《感冒样症状居家照护教学卡》（23 卡），金标 kb-gold-025/026 钉住命中

## 仍拒绝 / 不变

- 诊断、开处方、个体片数、停药换药：`MEDICATION_SAFETY` 无证据仍 `EVIDENCE_REQUIRED` + `escalate=true`；
- 知识有命中但未引用仍 `EVIDENCE_REQUIRED`；伪造引用仍 `CITATION_NOT_FOUND`；
- 禁止编造病毒名/病例数；无购药问诊导流。

## 回滚

`git revert` 相关提交即可；无迁移、无配置变更。
