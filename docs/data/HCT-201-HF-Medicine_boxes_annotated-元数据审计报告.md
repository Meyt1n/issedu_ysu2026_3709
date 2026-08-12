# HCT-201 Hugging Face Medicine_boxes_annotated 元数据审计

> 审计日期：2026-08-08。本文只记录公开仓库元数据，不下载、不提交图片、标注正文或模型权重。

## 来源

- 页面：[Malek-Messaoudi/Medicine_boxes_annotated](https://huggingface.co/datasets/Malek-Messaoudi/Medicine_boxes_annotated)
- 公开仓库提交：`c32be90ad070c64f72c5ac41c95409b3edda4f09`
- 页面声明许可证：MIT
- 页面声明用途：药盒目标检测；README 声称包含 train/val/test 和 YOLO 标签

## API 实际文件清单

通过 Hugging Face 数据集 API 的递归文件清单核验：

| 项目 | 实际值 |
|---|---:|
| 文件总数 | 41 |
| JPEG 图片 | 38 |
| 图片总大小 | 6,303,106 bytes |
| YOLO `.txt` 标注 | 0 |
| 图片所在分组 | 38 张全部在 `test/images` |
| `train/images` | 空 |
| `valid/images` | 空 |

## 决策：`QUARANTINED`

该候选不能进入 HCT-201 或 HCT-203，原因如下：

1. README 声明有 train/val/test 和 YOLO 标注，但实际公开树没有训练/验证图片，也没有标签文件；
2. 无法复现训练/验证/测试划分、类别分布、标注覆盖率或实体分组；
3. 页面 MIT 标识不等于底层图片来源、第三方包装内容和隐私权已被独立核实；
4. 当前只能作为待联系作者核实的线索，不能把 38 张测试图当作完整数据集。

## 解禁条件

- 作者或来源方提供完整版本、训练/验证/测试文件清单及哈希；
- 标签文件、类别映射、分组规则和原始数据许可可复核；
- 完成 PII/EXIF、重复/近重复、实体泄漏和删除传播审计；
- 按 `annotation-spec-v1` 补齐包装/条码/OCR 字段边界，并完成 R3 复核。
