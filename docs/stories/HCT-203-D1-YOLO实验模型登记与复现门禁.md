# HCT-203-D1 YOLO 实验模型登记与复现门禁

- Issue：[#112](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/112)
- Parent：Related to [#50 HCT-203](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/50)
- FR/NFR：FR-03、NFR-05、NFR-06
- 风险：R3
- 状态：进行中
- 负责人：Meyt1n
- 复核人：Shen-huang-123
- 基线：GitHub `master` 提交 `df9ac09e567225149770dc7381eced4f81ad6685`

## 用户价值和范围

本增量把已存在于仓库外的 YOLO11n 药盒辅助定位实验登记为可审计候选，让 Demo
和后续开发能够读取明确的版本、指标、失败样例和禁用原因。登记不等于批准：HCT-201
数据仍为 `QUARANTINED_UNRELEASED`，家庭运行端仍使用
`vision_model_version=unavailable`。

允许修改：

- `docs/stories/HCT-203-D1-*`；
- `docs/model-registry/HCT-203-*` 和 `docs/model-cards/HCT-203-*`；
- `scripts/hct203_model_registry_audit.py`；
- `scripts/hct203_benchmark.py`；
- `scripts/hct203_train_yolo.py` 及其数据 YAML dry-run 测试；
- `tests/unit/test_hct203_model_registry_audit.py` 和 `test_hct203_benchmark.py`；
- `docs/vibe-coding/12-需求追踪矩阵.md`。

明确不做：不在仓库内自动重跑训练，不提交图片、标签、模型权重、缓存、本机路径或真实健康数据；
不批准 HCT-201，不关闭父 Issue #50，不让 YOLO 替代 OCR、条码或人工确认。

## 输入、输出和异常

输入是训练机外置实验的 `args.yaml`、权重 SHA-256、脱敏评测摘要和阈值报告。输出是
仓库内不含路径/媒体的 JSON 模型登记、模型卡和审计器。

- 字段、哈希或困难负样本证据缺失：审计失败；
- 登记声称 `APPROVED`、`RELEASED` 或 `PRODUCTION`：审计失败；
- 登记含 Windows/UNC 绝对路径：审计失败；
- 原训练代码没有提交：必须保留 `PARTIAL_UNTRACKED_ORIGINAL_CODE`，不得伪装为完整复现；
- 受控训练机可通过 `--weights <外置权重>` 计算并比对真实制品 SHA-256；不一致时命令
  非零退出并输出 `effective_model_status=UNAVAILABLE`，调用方必须禁止加载。审计器不改写历史登记。

## Given / When / Then

- [x] Given 脱敏实验登记，When 运行审计器，Then 必填字段、哈希、未发布状态和外置权重约束通过；
- [x] Given 登记改成发布状态或加入本机路径，When 运行单元测试，Then 返回对应失败代码；
- [x] Given 已知两个困难负样本误检，When 读取登记和模型卡，Then 两个失败均保留且不会被总体高指标遮蔽；
- [x] Given 原始训练代码未跟踪，When 检查复现状态，Then 明确记录为部分复现及发布阻断；
- [x] Given 受控训练机提供数据 YAML；When 执行 `hct203_train_yolo.py --dry-run`；Then 校验 train/val、可选独立 test、类别数、seed 和训练配置，并只写路径脱敏 manifest；
- [ ] Given PR Required Checks 通过，When 维护者完成 R3 风险与回滚复核并 merge，Then 本子任务可关闭，但 #50 继续开放。

## 验证和人工验收

```powershell
uv sync --frozen
uv run ruff check scripts/hct203_model_registry_audit.py tests/unit/test_hct203_model_registry_audit.py
uv run pytest tests/unit/test_hct203_model_registry_audit.py
uv run python scripts/hct203_model_registry_audit.py --registry docs/model-registry/HCT-203-yolo11n-experimental-v1.2.json
uv run python scripts/hct203_model_registry_audit.py --registry docs/model-registry/HCT-203-yolo11n-experimental-v1.2.json --weights <受控训练机外置权重>
python scripts/hct203_benchmark.py --weights <外置权重> --images-dir <候选测试图目录> --device cpu --output <仓库外报告>
python scripts/hct203_benchmark.py --weights <外置权重> --images-dir <候选测试图目录> --device 0 --output <仓库外报告>
uv run pytest
git diff --check
```

人工验收检查登记与模型卡均显示 `EXPERIMENTAL_UNRELEASED`，权重不在 Git；使用受控外置
权重运行实哈希校验并取得 `VERIFIED`；两个困难负样本误检、完整 OCR/条码/融合性能未测、
未批准数据和原训练代码未跟踪均为可见阻断。

性能实测使用 147 张候选测试图：CPU P95 111.592 ms、11.103 图/秒、峰值 RSS
462,049,280 bytes；GPU P95 19.056 ms、62.621 图/秒、峰值 RSS 835,166,208 bytes、CUDA
allocated 69,124,096 bytes。报告只保存在受控训练机并登记哈希；它不是获批固定集或完整 OCR
管线性能。

## 风险和回滚

主要风险是高 mAP 被误读成正式能力。缓解方式是审计器禁止发布状态、模型卡保留失败样例，
并明确 YOLO 只建议 OCR 裁剪区域。回滚时删除本次登记、脚本和文档；运行端继续使用
`vision_model_version=unavailable`，不加载任何外置权重。

## 2026-08-22 验收补充

新增 `scripts/hct203_release_gate.py`，把 HCT-201 批准固定集、独立评估、hard-negative、报告哈希和回滚演练收成
`READY_FOR_R3_REVIEW` 门禁。该脚本不会修改 registry 或发布权重；当前实验登记仍因数据集未批准而阻塞。

## 2026-08-24 流程补充

HCT-203-D3 新增正式独立评估、回滚快照校验、人工 R3 checklist 和
`PUBLISHED_AUXILIARY_ONLY` 发布清单。机器门禁通过仍只代表材料可进入 R3；当前仓库没有批准固定集、
正式外置权重和真实 R3 记录，因此本 Story 的最后一项仍未完成，运行端继续保持
`vision_model_version=unavailable`。

当前维护者已通过 HCT-203-D3 waiver 批准该候选以 `PUBLISHED_AUXILIARY_ONLY` 形式发布；这不改变本 Story
对实验登记、候选 test 集和 hard-negative 误检的历史记录，也不代表正式固定集或 R3 验收通过。
