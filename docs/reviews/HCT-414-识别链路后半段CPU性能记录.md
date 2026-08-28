# HCT-414：识别链路后半段 CPU 性能记录

- Issue：[#246](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/246) 剩余项**第 2 条**「OCR / 条码 / 融合 / 人工复核交接的全链路 CPU P95」
- 日期：2026-08-28
- 分支：`codex/hct-414-fullchain-perf`（基于 `origin/master` `dce8bee`）
- 负责人：Shen-huang-123
- 复核人：维护者合并时完成最终复核
- 结论：**#246 仍不得关闭**；本增量把第 2 条从「完全未测」推进到「条码解码 / 证据归一化 / 候选融合三级已实测，OCR 与人工复核交接仍未测」

## 这一增量补的是哪一段

既有 `scripts/hct414_video_perf.py` 只覆盖「容器解码 → 间隔抽帧 → 近重复剔除 → 逐帧质量门控」，
它的 `stages_not_measured` 明确列着 OCR、条码、融合、人工复核四项未测。本增量新增
`scripts/hct414_fullchain_perf.py`，接着往下测**真实实现**的三级：

| 阶段 | 被测实现 | 是否真实 |
|---|---|---|
| 条码解码 | `ai.vision.local_ocr.LocalBarcodeDecoder.decode`（opencv-contrib `BarcodeDetector` + `QRCodeDetector`） | ✅ 真实解码 |
| 证据归一化与字段解析 | `ai.vision.evidence_pipeline.process_evidence` | ✅ 真实实现 |
| 候选融合与主数据匹配 | `ai.vision.candidate_fusion.fuse_evidence` | ✅ 真实实现 |
| OCR 推理 | `ai.vision.local_ocr.LocalPaddleOCR` | ❌ **未测**，见下 |

## 实测结果（2026-08-28，30 样本）

环境：Windows 10.0.22631，32 逻辑核，Python 3.11.15，`opencv-contrib-4.14.0`。

| 阶段 | P50 (ms) | P95 (ms) | Max (ms) |
|---|---|---|---|
| `barcode_decode` | 5.624 | **6.179** | 6.262 |
| `evidence_normalize` | 0.087 | 0.123 | 0.323 |
| `fusion_match` | 0.083 | 0.110 | 0.142 |
| **chain（三级合计）** | 5.826 | **6.481** | 6.689 |

链路 P95 **6.481 ms**，预算 **2000 ms**，在预算内。资源：进程 RSS 由 22.504 MB 增至 50.594 MB，
**增量 28.09 MB**（主要是首次导入 opencv 与 pydantic 模型）。

成本几乎全部在条码解码（占链路 P95 的 95%）；归一化与融合是纯 Python 字符串/评分运算，
两级合计不到 0.25 ms。**这意味着后半段的真实瓶颈会是 OCR，而 OCR 恰恰是本次没测到的那一级。**

正常样例的融合终态为 `MATCHED`，且 `requires_human_confirmation=true`、
`health_event_allowed=false` —— 匹配成功也不直接写健康事件，与 FR-03 的四状态语义一致。

## 夹具

按 EAN-13 模块图案直接绘制的合成条码（`4006381333931`，与 `tests/unit/test_hct206_candidate_fusion.py`
同一测试值），不依赖任何第三方条码编码库：

- 文件：`barcode-4006381333931.png`，12 094 字节
- SHA-256：`d8778a84a03512bba3e6b9aec20e714ed8be27690271d5736c5d222dcc5c0467`
- 命中渲染参数：`module_px=2`、`height=180`

**渲染参数是实测扫出来的，不是写死的魔法值。** opencv 的 `BarcodeDetector` 对模块宽度/高度比例
相当敏感：同一段编码在 `module_px=2` 可解码，在 3、4、5、6、8 全部失败。因此探针在生成夹具时
按候选表逐个尝试并把命中的参数写进报告；一个都不命中就直接以非零退出码阻断，不允许"静默跳过条码级"。
这条敏感性本身也值得注意——真机照片的条码尺度若落在不可解码窗口外，解码会失败而不是给出低置信结果。

## 受控拒绝样例（4/4 全部按预期拒绝）

| 样例 | 实测终态 | 实测原因 | `health_event_allowed` |
|---|---|---|---|
| 条码校验位错误（`4006381333932`） | `REVIEW` | `BARCODE_INVALID_CHECKSUM` | false |
| 主数据不可用 | `UNKNOWN` | `MASTER_DATA_UNAVAILABLE`、`NO_MASTER_CANDIDATE` | false |
| 空白图无条码 | 解码返回 0 个候选（不抛异常） | — | false |
| 名称与主数据冲突 | `CONFLICT` | `EVIDENCE_CONFLICT` | false |

四条都在写入健康事件之前被拦住。报告若出现"本应拒绝却被接受"，探针以非零退出码阻断。

## 为什么 OCR 没测

本机未安装 `paddleocr`，`LocalPaddleOCR.available` 为 `false`，报告里记录了确切原因
（`ModuleNotFoundError: No module named 'paddleocr'`）。

**没有硬跑，是有意的**：`local_ocr.py` 的设计是「缺依赖时返回空 token 并记录降级模式」，
硬跑只会测到那条降级路径的耗时（≈0），把它写成"OCR 的 P95"是错的。因此报告用
`stages_not_measured` 显式披露，单元测试也断言这条披露必须存在
（`test_ocr_is_disclosed_not_silently_skipped`）。

链路里注入的 OCR token 是**合成的**，只为让归一化与融合两级跑在真实实现上；
报告的 `ocr_engine_version` 因此标为 `synthetic-ocr`，不冒充真实 OCR 输出。

## 未覆盖（本记录不能声明的）

1. **OCR 推理成本** —— 需要安装 paddleocr（PaddlePaddle 体积大，且本机未验证可用）；
2. **人工复核交接** —— 需要 API + 数据库，属端到端联调，不在本探针范围；
3. **并发与多主机压测** —— #246 剩余项第 4 条，仍未做；
4. **准确率与阈值校准** —— 取决于 HCT-201（[#48](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/48)）授权固定集，未发布；
5. 未测真机采集样本过这三级（真机容器与编码证据见[真机采集容器与编码证据](HCT-414-真机采集容器与编码证据.md)，
   其中相机 HEVC 样本也尚未过服务端抽帧）。

因此 `release_status` 固定为 **`DEMO_ONLY`**，`release_blockers` 逐条列出上述阻断项。

## 安全、隐私与回滚

- 夹具是程序绘制的合成条码图案，**无药品实拍、无处方、无家庭健康数据**，运行结束即删、不入库；
- 报告只记录哈希、渲染参数、时延、内存与硬件标识，不记录任何健康正文；
- `artifacts/` 已被 `.gitignore` 覆盖，报告 JSON 不入库，与既有 `hct414-video-perf.json` 一致；
- 回滚：删除探针脚本、测试与本记录即可，不影响 `src/` 任何运行时行为。

## 自动验证

```text
python -m ruff check scripts/hct414_fullchain_perf.py tests/unit/test_hct414_fullchain_perf.py
python -m pytest tests/unit/test_hct414_fullchain_perf.py            # 9 passed
python scripts/hct414_fullchain_perf.py --samples 30                 # 退出码 0
```

本机以仓库 `.venv`（Python 3.11.15）代替 `uv`；`--basetemp` 指向可写目录以绕开本机
`%TEMP%` 权限限制（与既有视频探针相同处置）。
