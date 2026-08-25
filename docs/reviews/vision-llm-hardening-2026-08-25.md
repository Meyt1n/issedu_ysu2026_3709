# 视觉 / LLM 安全加固增量（2026-08-25）

- **分支**：`cursor/vision-llm-hardening-a666`
- **绑定**：FR-03 / FR-08 / NFR-04；维护性加固；后续 Story HCT-442 / HCT-443 已建档
- **前置**：#410 五项逻辑修复已合入

## 本增量落地

| 顺序 | 项 | 变更 |
| --- | --- | --- |
| 1 | 复核 payload 白名单 | `MedicationReviewPayload`（extra=forbid）；confirm 须属于任务候选；correct 拒绝脏字段 |
| 2 | 安全词表统一 | 新建 `src/ai/safety/lexicon.py`；分类 / 跟进 / 边界拒答共用；补口语近义 |
| 3 | 结构化输出校验 | `HealthAssistantOutput` 字段级校验 + Ollama `format` JSON schema；黑名单仍作兜底 |
| 4 | 融合阈值去 demo | 默认切到冻结合成校准值 `fusion-thresholds-calibrated-v1`；登记 `docs/model-registry/HCT-206-fusion-thresholds-calibrated-v1.json`；`hct206_calibrate.py --register` |
| 5 | RAG 召回 | 查询侧药名别名扩展 + 中文 trigram；检索走 `_query_tokens` |
| 6–7 | 依赖项 | Story HCT-442（分类双通道）、HCT-443（检索抽象）已建，不硬做运行时 |

## 非目标 / 限制

- 校准阈值 `production_eligible=false`，不得宣称为正式药品识别发布
- HCT-442/443 仅文档立项，待 HCT-402 与单独架构排期

## 回滚

按提交 `git revert`；无迁移。阈值回退可将 `FusionThresholds` 默认改回旧值并删除 registry 条目。
