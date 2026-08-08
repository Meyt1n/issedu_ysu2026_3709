# HCT-201 Roboflow drug-name-detection 元数据审计

> 审计日期：2026-08-08。本文只记录公开页面元信息，不下载、不提交图片、标注正文或模型权重。

## 来源

- 页面：[drug-name-detection](https://universe.roboflow.com/kabul-university-evptq/drug-name-detection)
- 数据集版本：[v1](https://universe.roboflow.com/kabul-university-evptq/drug-name-detection/dataset/1)，生成时间：2023-08-15
- 发布者：Kabul University
- 许可证：CC BY 4.0
- 任务：Object Detection

## 页面可复核事实

| 项目 | 页面值 |
|---|---:|
| 总图像 | 1,823 |
| 训练集 | 1,276（70%） |
| 验证集 | 365（20%） |
| 测试集 | 182（10%） |
| 类别数 | 1 |
| 类别 | `drug-name` |
| 自动预处理 | Auto-Orient；Stretch 到 640×640；Grayscale |
| 增强 | 无 |

## HCT-201 决策

`CONDITIONAL_ASSIST_ONLY`。该源可以辅助药名文字区域的预标注或格式转换，但不能直接成为 HCT-201 的完整批准数据集，原因是：

1. 只有 `drug-name` 一个类别，缺少 `medicine_box`、`barcode_region`、规格、厂家、批号、有效期和包装类型的证据；
2. 页面给出的训练/验证/测试划分不能证明按药品实体、包装、拍摄会话或相邻帧分组，必须重新审计并重划分；
3. 灰度化和 640×640 拉伸可能改变颜色、细粒度文字和条码结构，不能直接用于验证本项目的彩色 OCR/条码链路；
4. 页面许可是 CC BY 4.0，但仍需保存版本快照、署名、修改声明，并确认数据中没有未授权的个人信息或第三方内容；
5. 页面没有提供本项目所需的七字段原始值、来源区域、系统置信度和模型版本契约。

## 接纳前必须补齐

- 获取可追溯的导出文件、文件哈希和下载时间；
- 确认原始图像是否可取得、是否已经灰度/拉伸、是否存在隐私或第三方内容；
- 检查标注格式、类别分布、重复/近重复和实体/会话泄漏；
- 将其转换为 `annotation-spec-v1`，保留 `drug_name_region` 为辅助区域，补齐包装/条码/OCR 证据或明确隔离为辅助子集；
- 通过负责人和 R3 复核人审阅后，才可进入 `APPROVED` 或 HCT-203 训练入口。

当前不把该候选与 Mendeley V3 合并为一个“完整数据集”，也不把 Roboflow 页面展示的模型指标当作本项目验收指标。
