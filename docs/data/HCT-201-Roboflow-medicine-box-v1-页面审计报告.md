# HCT-201 Roboflow medicine-box-detection v1 页面审计

> 审计日期：2026-08-11。本文只记录公开页面可见的元信息，不下载、不提交图片、标签或模型权重。

## 1. 来源与可见事实

| 字段 | 事实 |
|---|---|
| 项目页 | <https://universe.roboflow.com/workspace-dcju6/medicine-box-detection-25jxw> |
| 数据集版本页 | <https://universe.roboflow.com/workspace-dcju6/medicine-box-detection-25jxw/dataset/1> |
| 公开版本 | v1，页面显示生成时间为 2025-10-29 |
| 类别 | 单一 `medicine_box` |
| 图片数量 | 1,453 |
| 页面划分 | Train 1,453（100%），Valid 0，Test 0 |
| 预处理 | Auto-Orient、Stretch 到 640×640 |
| 增强 | 页面显示未应用增强 |
| 页面许可证 | CC BY 4.0 |
| 项目描述 | 页面未提供项目描述 |

## 2. 当前没有被公开页面证明的事项

公开页面没有给出以下正式训练所需证据：

- 逐图原始来源、作者、采集日期、设备和会话信息；
- 逐图训练授权或独立训练同意；
- 手写内容、背景、EXIF 和其他个人信息的检查结果；
- 删除/撤销请求联系人、派生制品删除传播路径和保留期限；
- 可审计的实体/包装对象分组键；
- 独立 fixed test、unknown 集及冻结哈希。

因此，页面的 CC BY 4.0 标记只能作为候选许可证线索，不能单独把 1,453 条记录标为 `APPROVED`。

## 3. HCT-201 决策

当前状态：`CONDITIONAL_EXPERIMENT_ONLY`。

允许：

- 在可信域外继续做实验训练、推理和 Demo；
- 保持 `EXPERIMENTAL_UNRELEASED` 模型登记；
- 继续使用 pHash 做近重复和泄漏风险筛查。

禁止：

- 把 Roboflow 页面 Train/Valid/Test 直接当作正式划分；
- 把 pHash、文件名或随机编号写成真实实体/会话键；
- 生成 `canonical/v1.3` 的 `APPROVED` 版本；
- 启动 HCT-203 正式训练或发布模型。

## 4. 需要向来源方索取的证据包

建议请求一个不含图片正文的 CSV/JSON 元数据包和书面授权说明，至少包含：

```text
sample_id
source_url
source_author
capture_entity_id
capture_session_id
capture_device_id
capture_date_or_release_group
license_or_consent_ref
deidentification_statement
delete_or_withdrawal_contact
retention_until
```

来源方无法提供实体/会话信息时，Roboflow 数据只能继续作为实验候选；不能自行推断这些字段。

