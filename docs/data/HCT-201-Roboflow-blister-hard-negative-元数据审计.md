# HCT-201 Roboflow blister hard-negative 候选元数据审计

> 状态：`CONDITIONAL_HARD_NEGATIVE`，不是已批准数据源；本文件只登记公开页面元信息，不包含图片、标签正文或下载制品。

## 1. 来源快照

| 字段 | 值 |
|---|---|
| 来源 | [yeer/blister-gzah5-3utqd](https://universe.roboflow.com/yeer/blister-gzah5-3utqd) |
| 目标版本 | [Dataset v1](https://universe.roboflow.com/yeer/blister-gzah5-3utqd/dataset/1) |
| 许可证声明 | CC BY 4.0 |
| 页面访问日期 | 2026-08-08 |
| 版本页样本数 | 670 |
| 版本页划分 | train 469 / valid 134 / test 67 |
| 类别 | `bad_blisters`、`blister`、`blister-opaque` |
| 版本页预处理/增强 | 均声明为无 |
| 项目总览样本数 | 约 1.4k（与版本页 670 不一致） |
| 当前决策 | `CONDITIONAL_HARD_NEGATIVE` |

## 2. 适用边界

该候选与当前模型在非纸盒 blister 样本上的误检类型相关，可用于严格“只检测纸盒”范围的 `unknown` hard-negative 探针。它不能用于：

- 补充 `medicine_box` 正样本或证明药品身份识别；
- 作为 HCT-201 的完整授权数据集；
- 代替真实实体、采集会话、设备和日期分组；
- 在没有逐图来源、隐私和人工复核证据时进入训练、验证或固定测试集。

如果产品最终将 blister 作为正式包装类别，则该候选不应被标记为负样本，而应重新按产品类别和标注规范评审；当前实验的“纸盒检测”边界必须先由项目负责人确认。

## 3. 接纳前置条件

在可信训练盘下载后，必须保存：

1. Roboflow 版本页、许可证和访问时间；
2. 导出格式、原始压缩包哈希、图片/标签清单和逐图来源信息；
3. 逐图 PII、EXIF、手写内容和背景检查结果；
4. 精确/近重复、实体/会话/设备分组与泄漏检查；
5. 由人工确认其确实是非纸盒目标的抽检记录；
6. 删除/撤销传播路径和 `delete_ref`；
7. 与当前 `medicine_box` 模型在相同权重、阈值和硬件上的误检率对照。

总览页与版本页的 1.4k/670 数量差异关闭前，样本状态保持 `QUARANTINED`，不能把页面的 CC BY 4.0 直接解释为所有图片已经完成本项目的隐私与训练授权核验。

## 4. 退出判定

- 通过逐图许可、隐私、重复、分组和抽检：可登记为 `APPROVED_UNKNOWN`，仅进入固定 unknown/hard-negative 评测；
- 另有明确训练用途、标注和撤销证据：才可评审是否进入训练增强批次；
- 数量、许可、图像内容或目标边界无法核实：保持 `QUARANTINED`，不得用阈值调高替代数据缺口。

