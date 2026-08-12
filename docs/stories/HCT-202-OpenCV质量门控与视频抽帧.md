# HCT-202 OpenCV 图片质量门控与视频抽帧去重

- Story：HCT-202
- GitHub Issue：父任务 [#49](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/49)；后端增量 [#108](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/108)；前端增量 [#110](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/110)
- FR/NFR：FR-03、NFR-05
- 阶段：P0-W3
- 风险等级：R2
- 当前状态：进行中（后端质量门控已合并；前端拍照/上传/重拍闭环已在 #110 实现并待合并；正式固定集校准仍未完成）
- 负责人：Meyt1n
- 复核人：维护者合并即完成人工复核
- 开始日期：2026-08-10
- 预计交付：2026-08-11
- 前置依赖：HCT-002 已完成；HCT-201 的正式数据集未完成，因此本增量只使用程序生成的固定样例

## 1. 用户价值与目标

用户主动拍摄药盒后，系统在 OCR、YOLO 和条码处理前检查图片是否清晰、曝光合理、反光可控且主体占比足够。低质量输入返回明确重拍提示，不能继续进入自动确认。短视频按固定时间间隔抽帧并去除近重复，只把可定位的候选帧交给后续 OCR-first 管线。

## 2. 范围与非目标

本增量实现版本化质量 Schema、OpenCV 图片解码、尺寸/清晰度/亮度/过暗/过曝/反光/边缘密度/主体占比/边缘裁切代理指标、四边形透视校正工具、视频固定间隔抽帧和 dHash 去重，以及调用方直接上传字节的本地质量 API。`PASS` 结果签发绑定操作者、文件摘要、配置版本和有效期的短期质量凭证；创建视觉任务必须在服务端验证该凭证。

本增量不训练或发布 YOLO，不执行 OCR/条码解码，不识别药品身份，不写入健康事件，不提交图片或模型权重，不把程序生成样例指标解释为真实场景阈值已校准。遮挡只能记录为“主体触边代理指标”，不能宣称已完成语义遮挡识别。

## 3. Given / When / Then 验收

- [x] Given 可解码图片，When 执行质量检查，Then 返回 Schema/配置版本、原图摘要、指标、阈值、决定、原因和重拍提示，且不覆盖原文件；
- [x] Given 模糊、暗光、过曝、反光、尺寸不足或无明显主体的合成样例，When 检查，Then 返回 `RETAKE` 且至少一个可执行原因；
- [x] Given 清晰且主体占比合理的合成样例，When 使用测试阈值检查，Then 返回 `PASS`；
- [x] Given 倾斜四边形，When 执行透视校正，Then 返回新图像且输入像素保持不变；
- [x] Given 带时间戳的重复视频帧，When 按固定间隔抽帧和 dHash 去重，Then 顺序、时间戳、来源帧和去重结果确定；
- [x] Given 扩展名/媒体类型不匹配或内容无法解码，When 调用 API，Then 返回受控错误，不泄露文件名或本机路径；
- [x] Given 质量结果为 `RETAKE`，When 后续任务读取结果，Then 不签发质量凭证且 `allow_downstream=false`；视觉任务缺少凭证时服务端拒绝；
- [x] Given 质量凭证被另一操作者、不同文件、不同配置使用，或已过期/篡改，When 创建视觉任务，Then 默认拒绝且不创建下游任务。

## 4. 允许修改范围

- `src/ai/vision/`
- `src/api/app/config.py`、`src/api/app/routes.py`、`src/api/app/schemas.py`
- `scripts/hct202_quality_demo.py`
- `.env.example`、`pyproject.toml`、`uv.lock`
- `tests/unit/test_hct202_quality_gate.py`、`tests/contract/test_hct202_quality_api.py`
- 本 Story、需求追踪矩阵、视觉 README 和 Demo 操作指南
- `docs/reviews/HCT-202-质量门控Demo性能记录.md`

不修改认证、授权、事件、规则、OCR、LLM 和数据库迁移。#110 允许修改前端质量采集组件、统一 API 客户端及为真实启动所需的 Python 导入路径和本机代理配置。

## 5. 验证、风险与回滚

验证命令：

```powershell
uv sync --frozen
uv run ruff check src/ai/vision src/api tests/unit/test_hct202_quality_gate.py tests/contract/test_hct202_quality_api.py
uv run pytest tests/unit/test_hct202_quality_gate.py tests/contract/test_hct202_quality_api.py
git diff --check
```

风险包括阈值对设备/背景过拟合、反光和遮挡代理误判、视频解码器差异及大文件资源消耗。处理方式是版本化阈值、限制采样数量、失败默认 `RETAKE`、保留原始文件引用且禁止自动确认。正式阈值必须在批准的固定质量集上重新校准并报告误拒绝、漏拒绝和性能。

回滚时移除质量检查路由和 `opencv-quality-demo-v1` 配置，视觉任务保持明确的预处理不可用状态；不得绕过质量门控自动写入健康事实。

## 6. 当前证据与剩余工作

- 质量模块、短期凭证和 API 契约测试：`24 passed`；
- 前端质量状态、multipart 客户端、竞态清理和现有页面测试：`17 passed`；
- 合成单图 100 次 P95：9.660 ms，详见[性能记录](../reviews/HCT-202-质量门控Demo性能记录.md)；
- 输入像素、文件和本地路径均不进入响应或日志，OpenCV 只在本机运行；
- 视频采用流式采样，最多检查 `max_selected_frames × 4` 个候选，返回帧数受请求上限约束。
- 质量 API 不读取已存储的其他用户文件；它只处理本次请求直接上传的字节。`PASS` 凭证默认 10 分钟有效，并绑定操作者、文件 SHA-256 和配置版本；当前 Demo 使用单进程内存密钥，API 重启后旧凭证安全失效，多 worker/正式部署必须迁移为持久化签名密钥或数据库质量记录。
- 浏览器端已验证 `RETAKE` 不上传、`PASS` 后核对同文件 SHA-256 并创建 `queued` 视觉任务；换图、清除或切换身份会清空旧凭证，任务失败时尽力清理刚上传的文件。页面不展示凭证、服务端路径或文件摘要。

Issue #49 尚不能关闭：真实固定质量集上的阈值校准、误拒绝/漏拒绝统计、真实视频编解码性能和持久化文件归属/质量记录仍需后续增量完成。
