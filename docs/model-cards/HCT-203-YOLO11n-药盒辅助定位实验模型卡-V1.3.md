# HCT-203 YOLO11n 药盒辅助定位实验模型卡 V1.3

> 状态：`EXPERIMENTAL_UNRELEASED`。本卡登记续训实验事实，不是模型发布批准。

## 身份与用途

| 字段 | 值 |
|---|---|
| 模型 ID | `hct-yolo11n-box-assist-experimental-v1.3` |
| Story / Issue | HCT-203-D2 / [#120](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/120) |
| 父任务 | [#50 HCT-203](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/50)，仍开放 |
| 任务 | 为 OCR 建议药盒裁剪区域 |
| 权重 SHA-256 | `fcda34dd22d25bc0720a8ff9f63022108bd14900e835bba23a8d04ffc7a35f92` |
| 权重大小 | 5,498,321 bytes |
| 制品位置 | 受控训练机，仓库外 |
| 当前运行回退 | `vision_model_version=unavailable` |

允许用途只有“建议 OCR 裁剪区域”和受控离线教学实验。禁止用它判断药品/SKU、覆盖 OCR 或条码证据、直接写入健康事实、触发用药规则，或做诊断、处方、停药、换药和剂量判断。

## 训练与复现

- 数据版本：`HCT-201-dataset-v1.2-annotation-reviewed-candidate`；状态：`QUARANTINED_UNRELEASED`；manifest SHA-256：`a0ffc701eed17a1a3e7ded8c2d1c6a14a8c881191d49e77c46f5915b4e52d312`；
- 从第 20 轮 `last.pt` 恢复，完成第 21–50 轮；YOLO11n、50 epoch、640×640、batch 16、seed 42、deterministic；
- `args.yaml` SHA-256：`501b5ea9e3be567e48a9990adc9eed2bbec77530ccb9dd16b06ea9818ed8cf77`；
- Python 3.9.13、Ultralytics 8.3.225、PyTorch 2.7.1+cu118、RTX 4060 Laptop GPU；
- 原始训练代码与续训脚本没有纳入仓库，复现状态仍为 `PARTIAL_UNTRACKED_ORIGINAL_CODE`。

## 独立 test 结果

候选测试集 147 张、145 个真值实例，confidence=0.25：

| Precision | Recall | mAP@0.5 | mAP@0.5:0.95 |
|---:|---:|---:|---:|
| 0.9864 | 1.0000 | 0.9950 | 0.9284 |

输入集合 SHA-256：`eeca28b6bfdea7b4549d87fa5dfd5c6aa67dcf43a17595183567e1832cd70eae`。这些指标来自未批准候选划分，只能描述实验，不能作为固定集发布结果。

## 困难负样本与阈值探针

| 样本 | 类型 | 0.25/0.50/0.75 | 0.90 |
|---|---|---:|---:|
| `hct201-v1-hard-negative-00-90370b074a64` | 非纸盒泡罩包装 | 1 次误检，最高置信度 0.8585 | 0 次 |
| `hct201-v1-hard-negative-01-440b01bd90f1` | 非纸盒输液袋 | 1 次误检，最高置信度 0.8461 | 0 次 |

0.90 只是探针结果，不是经批准固定集校准出的发布阈值。两张困难负样本覆盖不足，仍是发布阻断。

## 性能

| 设备 | 平均延迟 | P50 | P95 | 吞吐 | 峰值内存 |
|---|---:|---:|---:|---:|---:|
| CPU | 113.681 ms | 116.998 ms | 137.319 ms | 8.793 图/秒 | 462155776 bytes RSS |
| RTX 4060 Laptop GPU | 16.250 ms | 15.755 ms | 20.930 ms | 61.333 图/秒 | 826814464 bytes RSS；69124096 bytes CUDA |

协议：147 张同一测试输入，batch 1、640 px、confidence 0.25、5 次预热。该报告只代表 YOLO 组件，不代表 OCR/条码/候选融合全流程性能。

## 发布阻断与回滚

当前阻断：HCT-201 没有 `APPROVED` 样本或获批 fixed/unknown 集；原始训练代码未跟踪；两张困难负样本在 0.75 及以下阈值均误检；R3 模型发布复核未完成。家庭端不得加载此模型，必须继续使用 `vision_model_version=unavailable`。

机器可读登记：[HCT-203-yolo11n-experimental-v1.3.json](../model-registry/HCT-203-yolo11n-experimental-v1.3.json)。哈希不一致或数据撤销时标记为 `REVOKED/UNAVAILABLE`，不得覆盖旧实验登记。
