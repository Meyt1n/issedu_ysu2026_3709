# HCT-203 YOLO11n 药盒辅助定位实验模型卡 V1

> 状态：`EXPERIMENTAL_UNRELEASED`。本卡登记实验事实，不是模型发布批准。

## 身份与用途

| 字段 | 值 |
|---|---|
| 模型 ID | `hct-yolo11n-box-assist-experimental-v1.2` |
| Story / Issue | HCT-203-D1 / [#112](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/112) |
| 父任务 | [#50 HCT-203](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/50)，仍开放 |
| 任务 | 为 OCR 建议药盒裁剪区域 |
| 权重 SHA-256 | `cedb5b52c1c2a71538c7f31bacc2d46aed0db2b0b7aec09eceb0d3525f5a7d1b` |
| 权重大小 | 5,499,089 bytes |
| 制品位置 | 受控训练机，仓库外；本卡不记录本机路径 |
| 当前运行回退 | `vision_model_version=unavailable` |

允许用途只有“建议 OCR 裁剪区域”和受控离线教学实验。禁止用它判断药品/SKU、覆盖
OCR 或条码证据、直接写入健康事实、触发用药规则，或做诊断、处方、停药、换药和剂量判断。

## 训练与复现状态

- 数据版本：`HCT-201-dataset-v1.2-annotation-reviewed-candidate`；状态仍为
  `QUARANTINED_UNRELEASED`；manifest SHA-256 为
  `a0ffc701eed17a1a3e7ded8c2d1c6a14a8c881191d49e77c46f5915b4e52d312`。
- 配置摘要：YOLO11n、50 epoch、640×640、batch 16、seed 42、deterministic、RTX 4060
  Laptop GPU；Ultralytics 8.3.225、PyTorch 2.7.1+cu118。
- 原始 `args.yaml` SHA-256：
  `be616107c53aef861c9776da7979ace4d983cc8d164d66591002e52090e6b940`。
- 原训练为仓库外实验，未绑定已提交的训练代码 SHA，因此复现状态只能是
  `PARTIAL_UNTRACKED_ORIGINAL_CODE`。本登记不能反向证明该实验已完整复现。

## 实验指标

测试候选共 147 张，其中 145 个药盒真值，置信度 0.25：

| Precision | Recall | mAP@0.5 | mAP@0.5:0.95 |
|---:|---:|---:|---:|
| 0.9864 | 1.0000 | 0.9950 | 0.9273 |

这些数值来自未批准候选划分，只能描述本次实验，不能作为正式固定集结果。

同一外置权重在 147 张候选测试图上按单图 batch 1、640 px、置信度 0.25、预热 2 次测量：

| 设备 | 平均延迟 | P50 | P95 | 吞吐 | 观测峰值内存 |
|---|---:|---:|---:|---:|---:|
| CPU | 90.014 ms | 87.718 ms | 111.592 ms | 11.103 图/秒 | 462,049,280 bytes RSS |
| RTX 4060 Laptop GPU | 15.915 ms | 15.700 ms | 19.056 ms | 62.621 图/秒 | 835,166,208 bytes RSS；69,124,096 bytes CUDA allocated |

输入集合内容哈希为
`eeca28b6bfdea7b4549d87fa5dfd5c6aa67dcf43a17595183567e1832cd70eae`。CPU/GPU 报告保存在
受控训练机仓库外，SHA-256 分别为
`cfc7f2b3821f9688cdbf7d8f2447fbdc941ca0ce9253cc6b65eaf4cc5881aa62` 和
`79beb621e907d5c4c1fe02b25d8c4a124b4cf425c70f46fa1ce650148e827a25`。这些是 YOLO
组件实验性能，不是 OCR/条码/融合全流程 P95，也不能解除正式固定集门禁。

## 失败样例与阈值风险

总体指标不能掩盖非目标误检：

- 非纸盒泡罩包装被误检，置信度约 0.8866；
- 非纸盒输液袋被误检，置信度约 0.7620；
- 在置信度 0.25、0.50 和 0.75 下，两张困难负样本均为 `2/2` 误检；0.90 时误检降为
  `0/2`，但正样本 Recall 降至约 0.8621。

因此不能用 YOLO 分数单独确认“这是药盒”。输出只能进入 OCR/条码/本地主数据多证据管线，
最终仍须人工确认。

## 发布阻断与回滚

当前阻断：HCT-201 没有 `APPROVED` 样本或获批固定/unknown 集；原训练代码未跟踪；困难
负样本覆盖只有 2 张且均误检；OCR/条码/融合全流程性能未测；R3 模型发布复核未完成。

仓库内机器可读登记位于
[HCT-203-yolo11n-experimental-v1.2.json](../model-registry/HCT-203-yolo11n-experimental-v1.2.json)。
审计失败、哈希不一致或数据撤销时，将候选标记为 `REVOKED`/`UNAVAILABLE`，家庭端维持
`vision_model_version=unavailable`；受控训练机使用审计器的 `--weights` 参数核对实际制品，
不一致时命令非零退出并给出 `effective_model_status=UNAVAILABLE`。不得覆盖旧登记或删除失败证据。
