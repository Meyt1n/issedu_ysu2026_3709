# HCT-205-D1：OCR-first 证据契约与离线字段归一化

## 1. 任务元数据

- 父 Issue：[#52](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/52)
- 子任务 Issue：[#122](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/122)
- FR/NFR：FR-03、NFR-03
- 阶段：P0-W4
- 风险：R2
- 负责人：Meyt1n
- 复核人：Shen-huang-123
- 分支：`codex/hct-205-ocr-evidence`
- 前置依赖：HCT-202、HCT-203、HCT-204

## 2. 目标与边界

本子任务为后续 OCR、条码和候选融合实现一个稳定的离线输入契约。OCR 保留原始文字、区域、置信度和引擎版本；条码作为独立证据并校验格式/校验位；YOLO 只保存包装或条码区域候选，不参与药品身份确认。

本子任务不运行具体 OCR/条码引擎，不接入云端药品服务，不接受真实健康数据，不创建健康事件，也不输出 `MATCHED`。HCT-206 负责候选融合和四状态判定，HCT-207 负责人工确认/修正。

## 3. 已交付

- `src/ai/vision/evidence_pipeline.py`：OCR token、条码候选、YOLO 区域、字段提议、字段证据、主数据候选和结构化 finding。
- `src/ai/vision/master_data.py`：按版本读取 `MASTER_DATA_ROOT/<version>.json`，校验 schema、版本、路径、批准 allowlist、审批状态、撤销状态和 SHA-256；缺失或篡改时返回不可用快照。
- 本地适配器 HMAC receipt：绑定任务 ID、上传文件 SHA-256、完整证据 payload、适配器 ID/版本/运行批次；API 只接受 allowlist 内适配器的有效 receipt。
- `POST /api/v1/vision-tasks/{task_id}/evidence`：验证任务创建者后，保存版本化证据结果；无主数据或证据冲突时安全降级。
- 前端 API 类型及 `submitVisionEvidence` 客户端方法。
- 单元测试和 API 契约测试，覆盖字段不得脱离证据、EAN 校验位、主数据候选、冲突/缺失和越权提交。

## 6. 本次功能增量：药品识别结果卡

- 候选卡从批准的本地主数据补充规格、厂家、有效成分、用途、注意事项和禁忌人群；这些字段仍属于未确认候选，不由 Ollama 自由生成。
- 前端明确显示识别置信度和主数据版本，并将操作按钮标为“确认保存”；只有用户点击确认后，复核 API 才创建 `medication_confirmed` 健康事件并进入后续规则投影。
- 未确认、拒识或无主数据的候选不会写入健康档案，也不会触发重复成分或相互作用规则。

## 4. 验收条件与证据

- [x] OCR/条码/YOLO 输入保留原始值、来源区域、置信度、通道版本和证据 ID。
- [x] 条码格式和校验位错误转成结构化 finding；未知条码不会伪造候选。
- [x] 字段保留原始值、规范化值、证据 ID、置信度、解析器版本、视觉模型版本和 `UNCONFIRMED` 状态。
- [x] 字段提议必须引用已有证据，不能提交图片中不存在的自由文本。
- [x] 离线主数据通过 `MASTER_DATA_ROOT` 下的版本化快照查询；快照不可用、完整性失败或无匹配时返回 `UNKNOWN`/`REVIEW`，不生成身份确认。
- [x] API 只允许任务创建者提交证据；结果写入既有 VisionTask，不创建健康事件。
- [x] API 拒绝无 receipt、错误签名、未 allowlist 的适配器；主数据版本必须同时通过服务端 allowlist 和快照审批/撤销状态校验。
- [x] `uv run pytest tests/unit/test_hct205_evidence_pipeline.py tests/unit/test_hct205_master_data.py tests/contract/test_hct205_evidence_api.py -q`：16 passed。
- [x] `uv run ruff check src/ai/vision/evidence_pipeline.py src/api/app/routes.py`：通过。

PR Required Checks、Relay Review 和维护者 merge 属于仓库合并门禁，不是本 Story 的技术验收项；维护者 merge 动作代表最终人工复核。

## 5. 已知限制与回滚

- 当前 API 只接收本地适配器已经产生的 OCR/条码/YOLO 结果，尚未绑定具体 PaddleOCR、ZXing 或 YOLO 推理进程；生产部署必须由本地受控适配器持有签名密钥，不能使用示例默认值。
- 当前仓库没有批准的药品主数据快照，默认 `master_data_version=unavailable`，返回 `MASTER_DATA_UNAVAILABLE`；不可据此确认药品。测试使用的主数据仅为运行时 synthetic fixture，未提交真实记录。
- 回滚时移除证据提交入口并将视觉任务降级为 `REVIEW`，保留既有任务结果和版本审计，不删除原上传文件。
