# 视觉模型与 LLM 逻辑审查记录（2026-08-25）

- **类型**：维护性审查与小步优化（无新增 Story；绑定既有 FR/NFR，见文末）
- **分支**：`cursor/vision-llm-optimize-a666`
- **执行代理模型 slug**：`claude-fable-5-thinking-xhigh`
- **审查范围**：视觉管线（质量门控 → 任务创建 → OCR/检测 → 候选融合 → 复核）、本地模型适配层、助手/LLM 工具调用与降级、RAG 知识检索与引用校验
- **事实源**：`docs/vibe-coding/02-技术方案.md`、`07-AI与RAG设计规范.md`、`04-系统架构与模块边界.md`、`08-测试与验收方案.md`、`src/ai/*/README.md`、相关 Story（HCT-206/207/401/403/405）

## 一、结构检查摘要

| 层 | 位置 | 职责（与文档一致性结论） |
| --- | --- | --- |
| 视觉管线 | `src/ai/vision/`（`quality_gate.py`、`ocr_engine.py`、`candidate_fusion.py`、`evidence_pipeline.py`、`local_models.py`、`video_frames.py`） | 质量门控、OCR-first 证据、四状态融合、YOLO/Qwen-LoRA 本地适配与签名校验；与 04/07 号文档描述一致 |
| 视觉任务/复核 | `src/api/app/vision_tasks.py`、`review.py` | 任务生命周期、唯一复核任务、确认/纠正/跳过写健康事件；与 HCT-207 Story 一致 |
| 助手/LLM | `src/api/app/tool_call.py`、`assistant.py` | Ollama 工具调用、问题分类、白名单工具、引用校验、结构化降级；与 HCT-403 一致 |
| RAG | `src/api/app/knowledge.py`（应用层实现）、`src/ai/rag/`（规范与设计） | 权限前置过滤、分块、TF-IDF 检索、引用回填 |
| 测试 | `tests/unit`、`tests/contract`、`tests/e2e`、`tests/safety` | 覆盖融合状态机、复核幂等、降级、危险输出拒绝 |

## 二、审查发现与处置

### 已落地（本 PR 修复，全部附回归测试）

| 优先级 | 发现 | 位置 | 修复 |
| --- | --- | --- | --- |
| P1 | RAG TF-IDF 的 IDF 分母用文档数、分子 df 按 chunk 统计，量纲不一致。当某词出现在超过可访问文档数的 chunk 中时 IDF 为负，含命中词的 chunk 被 `score > 0` 过滤掉，检索错误降级为 `NO_RELEVANT_RESULTS`，助手因此对本可回答的问题拒答 | `src/api/app/knowledge.py::retrieve` | 改为平滑的 chunk 级 IDF `log((1+n_chunks)/(1+df))+1`，命中词得分恒 ≥ 1；新增回归测试 `test_common_term_across_many_chunks_still_retrieved` |
| P1 | `classify_question` 未覆盖裸高危词（“剂量”“怎么吃”“漏服”“补服”“过量”“误服”），此类问题落入 `GENERAL`，绕过 `MEDICATION_SAFETY` 要求的成员事实+已审核知识双证据路由，模型可能凭先验作答（违反 07 号规范“证据不足不强答”） | `src/api/app/tool_call.py::classify_question` | 扩充 `MEDICATION_SAFETY` 关键词表；新增参数化分类测试 |
| P1 | 本地 LLM 字段抽取的反幻觉校验把所有证据拼成一个 haystack 再做子串检查，跨两条证据“拼接”出的值可通过本地防线，违反文档承诺的“值必须逐字来自其所引用的单条证据”（服务端管线会二次拦截，属纵深防御缺口） | `src/ai/vision/local_models.py::QwenLoraFieldExtractor.extract_fields` | 改为仅在其引用的 `evidence_id` 对应原文中做逐字子串校验；新增测试 `test_llm_drops_value_spliced_across_evidence_items` |
| P2 | `confirm_review` 被直接调用（绕过 HTTP 路由校验）时，零候选的 UNKNOWN 任务可确认成功并写入空 payload 的 `medication_confirmed` 健康事件 | `src/api/app/review.py::confirm_review` | 应用层补充空候选守卫，返回 422 `REVIEW_CANDIDATE_REQUIRED`；新增测试 `test_confirm_without_candidate_is_rejected` |
| P2 | Ollama 客户端对确定性 4xx（如模型名不存在的 404）也按重试预算重试，只是拖慢调用方等待的结构化降级响应 | `src/api/app/tool_call.py::OllamaClient` | 4xx（408/429 除外）立即停止重试；5xx/超时/连接错误仍按预算重试；新增两条重试行为测试 |

### 建议后续（本次未改，说明原因）

| 优先级 | 建议 | 原因未在本 PR 处理 |
| --- | --- | --- |
| P2 | RAG 检索目前为应用层 `knowledge.py` 内的 TF-IDF 实现，`src/ai/rag/` 主要是规范文档。若后续引入向量检索，建议先补一个检索接口抽象再替换实现 | 属结构性重构，超出“最小必要”审查范围，且现有实现修复后行为正确 |
| P2 | `classify_question` 为关键词表方案，边界外的近义表述（如口语化“吃错药了”）仍可能漏分类。建议在 HCT-402 微调落地后用模型分类 + 关键词兜底的双通道 | 依赖尚未完成的 HCT-402 训练交付物，当前只能扩词表（已做） |
| P2 | 复核确认/纠正的候选 payload 字段（`drug_name` 等）目前只做非空校验，建议在写入健康事件前用 Pydantic 模型收紧字段白名单 | 需与健康事件契约（HCT-103/HCT-435）联动评审字段口径，避免单方面收紧造成兼容断裂 |

## 三、测试证据

```bash
uv run pytest tests/unit/test_hct207_review.py tests/unit/test_hct401_knowledge.py \
  tests/unit/test_hct403_tool_call.py tests/unit/test_local_model_adapter.py -q
# 111 passed

uv run pytest tests/unit tests/contract -q
# 全部通过（3 skipped，与本改动无关的既有跳过）

uv run pytest tests/e2e/test_hct405_failure_degradation.py tests/safety -q
# 150 passed

uv run ruff check <全部改动文件>
# All checks passed!
```

## 四、回滚方式

全部改动集中在单分支单主题提交，`git revert` 对应 commit 即可整体回滚；无迁移、无配置、无数据变更。逐项回滚可按文件粒度还原（每处修复相互独立）。

## 五、关联 FR/NFR

- **FR-03 多证据视觉录入**：本地模型逐字证据校验、复核空候选守卫
- **FR-08 本地证据型助手**：RAG IDF 修复（检索不再错误拒答）、用药安全分类扩词
- **NFR-04 可靠性/降级**：Ollama 确定性错误快速进入结构化降级

无新增 Story；本文件与 PR 描述即为本次维护性审查的可定位证据。
