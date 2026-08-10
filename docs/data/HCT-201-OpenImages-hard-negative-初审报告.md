# HCT-201 Open Images hard-negative 初审报告

> 审计日期：2026-08-10
>
> 状态：`QUARANTINED_PRELIMINARY_REVIEW`。本报告只保存公开来源元数据、哈希结论和初审建议，不包含图片、标签、模型权重或本机路径，也不代表 R3 复核通过。

## 1. 目的与边界

当前 YOLO11n 候选模型在两个仅测试 hard negative 上均产生 `medicine_box` 误检。为验证“YOLO 只辅助 OCR 裁剪、不能单独确认药盒”的边界，从 Open Images V6 validation 筛选 20 张非纸盒候选，作为下一版困难负样本的隔离来源。

这批候选不补充药品身份、OCR 字段或条码真值，不改变 OCR-first 主链路，也不能解除 HCT-201 的来源审批、真实实体分组、删除传播、固定集和 unknown 集阻断。

## 2. 来源与完整性

| 字段 | 结果 |
|---|---|
| 来源 | Open Images V6 validation |
| 官方下载说明 | <https://storage.googleapis.com/openimages/web/download.html> |
| 官方数据说明 | <https://github.com/openimages/dataset/blob/main/READMEV3.md> |
| 筛选范围 | 15 张来源标签 `Bottle`，5 张来源标签 `Plastic bag` |
| 初始筛选 | 同图无 Open Images `Box` 框；逐图元数据 License 为 CC BY 2.0 |
| 下载完整性 | 20/20 文件存在且 SHA-256 与隔离 manifest 一致 |
| 隔离 manifest SHA-256 | `da0a7b5e7bfedee40317583d4377ee54204e8a04ad3edc4ffe3ac67684974c0e` |
| 正式状态 | 20/20 `QUARANTINED`；未创建空标签，未进入 train/validation/test |

Open Images 官方说明要求逐图核验许可；因此聚合元数据中的 CC BY 2.0 不能直接替代当前落地页检查。

## 3. 逐图初审

| source_image_id | 目标/隐私初审 | 当前许可核验 | 初审建议 |
|---|---|---|---|
| `00a36f96e31731c4` | 屏幕内容可见 | Flickr 落地页 CC BY 2.0 | `REJECT_PRIVACY` |
| `02deba0102b5ce2a` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0 | `APPROVE_HARD_NEGATIVE` |
| `031244297d177089` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0 | `APPROVE_HARD_NEGATIVE` |
| `049720d842de2d3e` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0；oEmbed 作者别名对应 | `APPROVE_HARD_NEGATIVE` |
| `04d9284ebdc41aeb` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0 | `APPROVE_HARD_NEGATIVE` |
| `06a4a9b49707a673` | 含多个纸盒/商品盒 | Flickr 落地页 CC BY 2.0 | `REJECT_TARGET_BOX` |
| `07f328166c0ebbf7` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0 | `APPROVE_HARD_NEGATIVE` |
| `09b27cac767ccc61` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 404；oEmbed 可读但不能替代许可页 | `REVIEW_REQUIRED` |
| `0d24b635e58e9dc0` | 未见目标纸盒或可识别个人信息 | 当前 Flickr 落地页为 All rights reserved，与旧元数据冲突 | `REVIEW_REQUIRED` |
| `10fd5df6c15ddcad` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0 | `APPROVE_HARD_NEGATIVE` |
| `11e636d22f2e9bd4` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0 | `APPROVE_HARD_NEGATIVE` |
| `13b6289aef7a24b7` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0 | `APPROVE_HARD_NEGATIVE` |
| `13d3f1e5893726a2` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0 | `APPROVE_HARD_NEGATIVE` |
| `1602934b52b119cc` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0 | `APPROVE_HARD_NEGATIVE` |
| `488ab15e2780bec9` | 含多个矩形商品盒 | Flickr 落地页 CC BY 2.0 | `REJECT_TARGET_BOX` |
| `4e24222b68123ef3` | 含大型纸盒且背景人物可识别 | Flickr 落地页 CC BY 2.0 | `REJECT_PRIVACY` |
| `527bec033e8298a5` | 未见目标纸盒；房间背景隐私不确定 | Flickr 落地页 CC BY 2.0 | `REVIEW_REQUIRED` |
| `7e25a4a33611d933` | 未见目标纸盒；商品/物流码未见个人信息 | Flickr 落地页 CC BY 2.0 | `APPROVE_HARD_NEGATIVE` |
| `14f3cf0bf538d81c` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0；oEmbed 作者别名对应 | `APPROVE_HARD_NEGATIVE` |
| `15c473ae47357d22` | 未见目标纸盒或可识别个人信息 | Flickr 落地页 CC BY 2.0 | `APPROVE_HARD_NEGATIVE` |

汇总：13 张建议 `APPROVE_HARD_NEGATIVE`，2 张 `REJECT_PRIVACY`，2 张 `REJECT_TARGET_BOX`，3 张 `REVIEW_REQUIRED`。这些是 Agent 初审建议；在 `Shen-huang-123` 完成 R3 逐图复核前，13 张建议通过样本也不能进入训练。

## 4. 重复与固定集隔离

- 20 张候选与 canonical/v1.2 的 1,453 条记录精确 SHA-256 重叠为 0；
- 使用 canonical/v1 相同的 64-bit pHash 算法，与 145 个 test 和 2 个 unknown 候选比较；
- 20 张候选的最近 pHash 汉明距离为 14–22，没有命中 `<=2` 的近重复阈值；
- 该结论只证明未发现当前算法定义下的重复，不等于来源实体/会话/设备分组已经解决。

## 5. 当前模型证据

隔离训练盘的 `HCT-201-dataset-v1.2-annotation-reviewed-candidate` 共 1,453 条，正式 `split` 仍全部为 `quarantine`。候选 manifest SHA-256 为 `a0ffc701eed17a1a3e7ded8c2d1c6a14a8c881191d49e77c46f5915b4e52d312`。

YOLO11n 50 epoch 候选实验在 147 张 test 上得到 Precision 0.9864、Recall 1.0000、mAP50 0.9950、mAP50-95 0.9273；但两个 hard negative 在置信度 0.25、0.50 和 0.75 下均被误检。置信度提高到 0.90 虽消除这两个误检，却把 Recall 降至 0.8621。因此不能靠单一阈值替代困难负样本和多证据复核。

权重不进入 Git。候选权重 SHA-256 仅登记为 `cedb5b52c1c2a71538c7f31bacc2d46aed0db2b0b7aec09eceb0d3525f5a7d1b`，不代表发布模型。

## 6. 下一步与回滚

1. R3 复核人逐项确认 13 张建议通过样本，填写复核人、日期、许可、隐私和目标排除结论；
2. 只有最终 `APPROVE_HARD_NEGATIVE` 才能创建空 YOLO 标签并进入新的训练候选；
3. 新 hard negative 只能加入 train，必须与既有 test/unknown 保持隔离；既有两个 test hard negative 不得进入训练；
4. 生成 canonical/v1.3 候选后重新运行许可、SHA/pHash、分组、固定集、unknown、删除传播和 manifest 审计，再用同一 test 比较误检；
5. 任一许可、隐私、目标污染、删除传播或 R3 复核失败时，继续隔离对应样本并保持 v1.2 不变。

回滚只需停用后续 v1.3 候选入口并恢复 v1.2 隔离 manifest；不得覆盖 v1.2 清单、报告或模型哈希。
