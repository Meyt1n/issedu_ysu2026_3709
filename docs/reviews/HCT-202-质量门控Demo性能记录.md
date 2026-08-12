# HCT-202 质量门控 Demo 性能记录

- 执行日期：2026-08-11
- 配置版本：`opencv-quality-demo-v1`
- 结果 Schema：`vision-quality-result-v1`
- 输入：程序生成的无敏感信息图片，不包含药品、处方或家庭健康数据
- 命令：`uv run python scripts/hct202_quality_demo.py --iterations 100`

## 环境

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 10 `10.0.22631` |
| Python | 3.11.15 |
| OpenCV | 4.14.0 |
| 处理器标识 | Intel64 Family 6 Model 183 Stepping 1, GenuineIntel |
| GPU | 未使用 |

## 合成样例结果

| 样例 | 决定 | 主要原因 |
|---|---|---|
| 清晰主体 | `PASS` | 无 |
| 模糊 | `RETAKE` | `BLURRY`、`NO_TARGET` |
| 暗光 | `RETAKE` | `TOO_DARK`、暗像素过多、无主体等 |
| 过曝 | `RETAKE` | `TOO_BRIGHT`、亮像素过多、`GLARE` 等 |
| 尺寸不足 | `RETAKE` | `IMAGE_TOO_SMALL` |

## 单图性能

在同一张 640×480 合成清晰图上连续执行 100 次：

| 指标 | 结果 |
|---|---:|
| P50 | 7.726 ms |
| P95 | 9.660 ms |
| 最大值 | 10.481 ms |
| 进程 RSS 增量 | 598,016 bytes |

该结果只覆盖质量指标计算，不包含磁盘上传、视频解码、YOLO、OCR、条码、LLM 或数据库耗时。

## 结论与限制

合成样例证明版本化 Schema、拒绝原因、重拍提示和 CPU 单图执行入口可运行。它不能证明真实药盒上的误拒绝率、漏拒绝率、反光/遮挡识别准确率或跨设备泛化；这些指标必须在 HCT-201 批准的固定质量集上重新校准。当前配置只能用于本地 Demo 和后续前端联调，不能标记为发布阈值。
