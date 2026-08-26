# HCT-414 视频抽帧 CPU 性能与证据记录

- 执行日期：2026-08-25
- 提交：`9a23ad53a165`
- 发布状态：**DEMO_ONLY**（HCT-201 授权固定集未发布，本记录不构成任何准确率结论）
- 结果 Schema：`vision-quality-result-v1`；门控配置版本：`opencv-quality-demo-v2-lenient-exposure`
- 输入：脚本本地生成的合成视频，不含药品实拍、处方或家庭健康数据；夹具不入库
- 命令：`uv run python scripts/hct414_video_perf.py --samples 10`
- 机器可读产物：`artifacts/hct414-video-perf.json`（`schema_version: hct414-video-perf-v1`）

本记录补齐父任务 [#246](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/246) 中 HCT-414-D2 明确留下的一项：**CPU 全流程 P95 性能报告**。功能实现分别在 [HCT-414-D1 #264](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/264)（媒体类型与质量凭证绑定）、[HCT-414-D2 #332](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/332)（抽帧 worker、时长上限、能力声明）与 [HCT-439 #389](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/389)（临时媒体留存与定期清理）中交付。

## 环境

| 项目 | 值 |
|---|---|
| 操作系统 | `Windows-11-10.0.22631-SP0` |
| 处理器标识 | `Intel64 Family 6 Model 183 Stepping 1, GenuineIntel` |
| CPU | 24 物理核 / 32 逻辑核 |
| 内存 | 31.7 GB |
| Python | 3.13.2 |
| OpenCV | 4.14.0（`opencv-python-headless`） |
| GPU | 未使用 |

## 被测阶段

已测：容器解码（`cv2.VideoCapture`）→ 间隔抽帧 → 近重复帧剔除 → 逐帧质量门控。

**未测**（如实声明，不得当作已验证）：OCR / 条码提取、候选融合与主数据匹配、人工复核交接。

## 合成夹具与延迟

预算：视频链路 P95 ≤ 8000 ms（与既有"本地视觉全链路 CPU P95 ≤ 8s"基线一致）。实测最差 P95 = **133.617 ms**，在预算内。

| 夹具 | 时长 | 抽帧间隔 | 解码帧 | 抽样帧 | 去重后 | 可用帧 | 决定 | P50 (ms) | P95 (ms) | Max (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| `sharp_5s_1fps_sampling` | 5s | 1000 ms | 75 | 5 | 1 | 1 | PASS | 42.516 | 46.45 | 46.45 |
| `varied_30s_at_duration_limit` | 30s | 1000 ms | 450 | 30 | 1 | 1 | PASS | 119.347 | 133.617 | 133.617 |
| `sharp_10s_dense_sampling` | 10s | 200 ms | 150 | 50 | 2 | 1 | PASS | 73.142 | 78.429 | 78.429 |
| `static_10s_duplicate_heavy` | 10s | 200 ms | 150 | 50 | 1 | 1 | PASS | 64.011 | 71.085 | 71.085 |

"解码帧 / 抽样帧 / 去重后"三列说明各阶段实际做了多少工作：**成本主要在容器解码**（30s 片段解码 450 帧约 119 ms），而合成画面高度自相似，近重复剔除会把 30 个抽样帧收敛到 1 个。真实手持拍摄会有更多帧进入逐帧打分，因此本表的逐帧打分部分是下界而非上界。

## 资源占用

| 项目 | 值 |
|---|---|
| 夹具磁盘占用 | 2720 KB（临时目录，运行结束即删除） |
| 进程 RSS 增量 | 45.7 MB |

## 受控拒绝样例

| 样例 | 期望 | 实测 | 结果 |
|---|---|---|---|
| `undecodable_container` | `VIDEO_DECODE_FAILED` | `VIDEO_DECODE_FAILED` | 已拒绝 |
| `empty_file` | `VIDEO_DECODE_FAILED` | `VIDEO_DECODE_FAILED` | 已拒绝 |
| `duration_exceeded` | `VIDEO_DURATION_EXCEEDED` | `VIDEO_DURATION_EXCEEDED` | 已拒绝 |
| `blurred_low_detail` | 决定 `RETAKE` | `RETAKE` | 已拒绝（不进入识别） |

四条都在进入识别前被拒绝，符合"非法/超限/无法解码/低质量不进入识别与健康事件"的验收条件。

## 夹具哈希

| 夹具 | SHA-256 | 大小 |
|---|---|---|
| `sharp_5s_1fps_sampling` | `9d1d8949bc9a38dffb66ff9bff074623254bc612ca0f1b3d0a99a78b74d84314` | 225 KB |
| `varied_30s_at_duration_limit` | `50852e3f558b53cd36d5a8446459a4ce39b2622bdaff4dec535355b03d114134` | 1344 KB |
| `sharp_10s_dense_sampling` | `7395013e82b6264baf4cb692177b848e6146774433dd15cfc797375a8a9218a0` | 428 KB |
| `static_10s_duplicate_heavy` | `8baa478c91fd817e4a8eb2a60ebceb5ecb3b51907bd9eea15fb6f4ead935639a` | 352 KB |

夹具由固定图案确定性生成；哈希随 OpenCV 编码器版本可能变化，比较时应同时核对上表的 OpenCV 版本。

## 已知限制

- 单机进程内探针，不是多主机或并发压测；
- 本地 `mp4v` 编码夹具，真机采集的容器/编码可能解码更慢；
- 画面为合成图案，质量分数**不是**准确率信号；
- 合成帧高度自相似，近重复剔除会收敛掉大部分抽样帧（见上表）；
- OCR、融合与人工复核交接未测，父任务的"全链路"结论仍不成立。

## 结论与阻断项

视频解码、抽帧、去重与逐帧质量门控在基础档机器上远低于 8s 预算，受控拒绝路径全部按预期拒绝。但以下仍是发布阻断项：

1. HCT-201 授权固定集未发布 —— 无准确率结论，状态保持 `DEMO_ONLY`；
2. OCR / 融合 / 人工复核交接的全链路 P95 未测；
3. 真机采集（Android WebView 上传的真实容器与编码）未测。
