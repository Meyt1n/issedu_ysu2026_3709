# HCT-414-D2 视频抽帧 worker 处理与服务端视频上限/能力声明

- Issue：[#332](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/332)（父任务 HCT-414 [#246](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/246)，解除 MOB-149 [#239](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/239) 的服务端阻塞）
- 需求绑定：FR-03 多证据视觉录入；NFR-01 安全、NFR-03 可追溯、NFR-04 降级可用、NFR-05 性能
- 负责人：zhang（agent: ZCode）；复核人：维护者（merge 即复核）
- 风险等级：R2（worker 视频分支异常只影响视频任务自身，图片路径不受影响；无迁移）
- 状态：待验收（代码与测试已完成，待 PR/复核）

## 用户价值

HCT-414-D1 之后服务端已能区分图片/视频任务并校验媒体类型凭证，但
`scripts/vision_worker.py` 只会处理单张图片：视频任务永远停在 queued，
移动端（MOB-149）拿不到帧级回执与人工复核交接。本切片补齐家庭受信域
worker 的视频抽帧处理，并为服务端补时长上限与能力声明，使 #239 具备
端到端联调条件。

## 范围与实现

- `src/ai/vision/video_frames.py`（新增，无重依赖）：`decode_video_frames`
  按采样间隔产出带像素的帧（供本地引擎使用）；`merge_frame_requests` 把
  逐帧 adapter 输出合并为单条 `EvidencePipelineRequest`——token/barcode/
  region id 加 `f<N>-` 帧前缀保持可追溯，`FieldProposal.evidence_ids` 同步
  重映射，跨帧重复条码保留最高置信度，列表按 schema 上限截断。
- `scripts/vision_worker.py`：识别 `task.media_type`，视频任务下载后抽帧
  （默认 1000ms 间隔、最多 8 帧，可用 `--video-sample-interval-ms` /
  `--video-max-frames` 调整）、逐帧运行本地引擎、合并后照常签名提交
  evidence，复用现有 succeeded→人工复核桥接；不改变任何确认边界。
- `src/ai/vision/quality_gate.py` + `src/api/app/routes.py`：
  `assess_video_file` 新增 `max_duration_ms`，元数据与实际采样时间戳双重
  校验，超限抛 `VIDEO_DURATION_EXCEEDED`（接口层 422，不签发凭证）；
  上限来自 `vision_video_max_duration_seconds`（默认 30s）。
- `src/api/app/config.py` + `/meta/capabilities`：新增
  `vision_video_tasks_enabled` 开关；开启时 `vision-task-video` 进
  available，关闭时进 unavailable，移动端可据此 fail-closed 隐藏视频入口。

## 顺带修复的两个既有缺陷（均在视频契约路径上必现）

1. `_file_digest` 只哈希前 8KB，而质量凭证绑定全量 sha256：任何 ≥8KiB 的
   媒体（真实手机照片全部命中）创建任务都会 `QUALITY_RECEIPT_MISMATCH`。
   已改为全量哈希，两侧口径一致（`src/api/app/vision_tasks.py`）。
   注意：跨版本幂等重试会因旧任务存的是 8KB 口径摘要而冲突，属一次性
   迁移语义，演示环境任务为短生命周期数据，不构成阻塞。
2. `.mp4`/`.mov` 魔数白名单只认 0x18/0x20（mp4）/0x14/0x18（mov）两种
   ftyp box 长度，OpenCV 与部分手机录制的 0x1c 等长度被误拒。改为结构化
   校验 ISO-BMFF ftyp box（长度 8..256 且 brand 为 `ftyp`），
   `src/api/app/file_upload.py`。

## 明确非目标

- 不实现视频/帧留存与定期清理策略、CPU P95 性能报告（留在父任务 #246）。
- 不改变 OCR、条码、候选融合、人工确认和健康事件边界；不做移动端 UI。
- 不提交真实视频、药品图片、模型权重或运行日志；测试仅用合成视频。

## 测试与证据

- 新增 `tests/contract/test_hct414d2_video_contract.py`（5 项）：
  能力开/关声明；真实合成 mp4 的质量门 happy path（含帧级摘要与凭证）；
  31s 视频被 422 `VIDEO_DURATION_EXCEEDED` 拒绝；端到端——质量凭证→视频
  任务创建→合并 evidence（帧前缀/条码去重/evidence_ids 重映射断言）→
  succeeded→唯一人工复核任务桥接。
- 新增 `tests/unit/test_hct414d2_video_frames.py`（4 项）：抽帧采样间隔/
  上限/垃圾输入受控错误；合并空列表/前缀/run_id。
- `uv run ruff check src/api tests migrations`：通过。
- `uv run pytest`（全量）：见 PR 描述与本 Story 验收记录。

## 部署影响与回滚

- 无数据库迁移；新配置项均有安全默认值。
- 回滚：`vision_video_tasks_enabled=false` 即可让客户端隐藏视频入口并停
  止声明能力；worker 视频分支可随提交整体还原，图片路径与人工复核边界
  不受影响。

## DEMO_ONLY 声明

按 HCT-414 要求，在 HCT-201 批准固定质量集/数据集证据之前，视频任务
能力仅用于本地演示，不声明生产识别性能；质量阈值与抽帧参数均为演示
基线。
