# HCT-203 YOLO11n 药盒辅助定位发布卡 V1.3

- 模型 ID：`hct-yolo11n-box-assist-experimental-v1.3`
- 发布状态：`PUBLISHED_AUXILIARY_ONLY`
- 发布方式：`MAINTAINER_WAIVER`
- 发布清单：[HCT-203-yolo11n-auxiliary-publication-v1.3.json](../model-registry/HCT-203-yolo11n-auxiliary-publication-v1.3.json)
- 来源登记：[HCT-203-yolo11n-experimental-v1.3.json](../model-registry/HCT-203-yolo11n-experimental-v1.3.json)
- 维护者批准：[HCT-203-maintainer-waiver.json](../reviews/HCT-203-maintainer-waiver.json)

## 能力边界

该模型只提出药盒或裁剪区域，供 OCR-first 流程使用。它不识别药品或 SKU，不覆盖 OCR、
条码或人工确认，不写入健康事实，不做诊断、处方、剂量、停药或换药判断。

家庭运行时默认不加载该模型；任何候选结果都必须人工确认，降级值仍为
`vision_model_version=unavailable`。

## 已登记候选指标

指标来自原实验登记的候选 test 集，不是本次重新执行的正式独立 test：

| 指标 | 值 |
|---|---:|
| 样本数 | 147 |
| ground-truth instances | 145 |
| precision | 0.9863945578 |
| recall | 1.0 |
| mAP50 | 0.995 |
| mAP50-95 | 0.9283653872 |
| 权重 SHA-256 | `fcda34dd22d25bc0720a8ff9f63022108bd14900e835bba23a8d04ffc7a35f92` |

## 已知限制和豁免

本次维护者批准豁免真实批准固定集、正式外置权重现场校验和单独人工 R3 记录。该豁免不删除
限制，也不把候选 test 集变成正式固定集。

登记的两个 hard-negative 均为误检：

- `hct201-v1-hard-negative-00-90370b074a64`：置信度 `0.8585256934`；
- `hct201-v1-hard-negative-01-440b01bd90f1`：置信度 `0.8460972309`。

因此本发布不得用于药品身份判断，只能作为受控的区域辅助候选。正式固定集、现场权重校验和
独立 R3 复核仍属于未完成的正式验收项。

## 回滚

发布清单绑定了上一版本 `vision_model_version=unavailable`。回滚调用现有
`/api/v1/model-version-bindings/{binding_id}/rollback` 契约，撤销候选并恢复上一绑定；
当前记录为 binding contract test evidence，不宣称已经完成生产部署环境演练。
