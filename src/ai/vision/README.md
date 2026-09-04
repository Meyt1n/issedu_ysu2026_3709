# HomeCare Twin Vision

视觉模块采用 OCR-first：先对用户主动拍摄的整张药品包装图做质量门控和 PaddleOCR，再用 YOLO11n 辅助检测药盒、药瓶、药板和条码区域。条码/二维码使用专用解码器，OCR 只作为码值兜底；药名、规格、厂家、批号和有效期的主要证据来自 OCR 文本框，而不是整盒图像分类。

YOLO 不得把每个 SKU 当作类别，也不得覆盖 OCR/条码原始结果。`drug_name_region`、`spec_region`、`expiry_region` 可以作为辅助裁剪或预标注类别，但不是 OCR-first 发布模型的必需类别。字段归类由规则、本地药品主数据和受约束的本地 LLM 完成；LLM 只能在已有 OCR token 中做语义解析/槽位填充，不能补写不存在的文字。

字段输出格式以 `docs/data/HCT-201-OCR字段提取契约-V1.md` 为准，必须保存原始值、来源区域、系统计算置信度、各处理阶段版本和确认状态。

输出必须允许 `MATCHED`、`CONFLICT`、`UNKNOWN` 和 `REVIEW`，并携带证据帧、框、字段来源、模型/阈值/OCR/条码/包装特征/主数据版本。高分不等于药品身份确认，正式入库必须人工复核；人工修正必须保留原预测、修正值、理由、操作者和训练同意状态。

视觉/OCR 任务默认在家庭可信域运行，不得把原图、视频帧、OCR 正文或候选上下文发送到云端。未知和冲突优先转人工，不以覆盖率换取自动通过。

HCT-206 候选融合只对 HCT-205 已存在的本地主数据候选排序。结果按版本化权重和阈值输出每个通道的支持、冲突、缺失、分数、证据 ID 和版本；`MATCHED` 仍要求人工确认，融合 API 永远返回 `health_event_allowed=false`。没有批准主数据、关键字段缺失、证据冲突、模型不可用或候选间隔不足时，只能降级为 `CONFLICT`、`UNKNOWN` 或 `REVIEW`。

## HCT-202 Demo 质量门控

`quality_gate.py` 提供 `opencv-quality-demo-v2-lenient-exposure`：图片返回尺寸、清晰度、曝光、暗/亮像素、反光代理、边缘密度、主体占比和主体触边代理指标，并给出 `PASS` 或 `RETAKE`、重拍提示及透视四边形。曝光门控对常见的白色药盒和白背景放宽，仅在整图明显过亮、亮部大面积裁切或反光同时导致细节不可用时拒绝。结果中的 `allow_downstream=false` 必须阻止后续自动确认。四边形校正只返回新的内存图像，不覆盖原始文件。

视频按固定毫秒间隔采样，使用 64-bit dHash 去除近重复帧，并限制候选帧数量。返回值只包含帧索引、时间戳、哈希和质量指标，不包含像素或本机路径。当前阈值只用于合成样例和 Demo 管线联调，不能当作真实药盒固定集校准结果。

质量 API 只分析调用方在当前请求中直接上传的字节，不通过 `file_id` 读取共享存储。严格模式下只有 `PASS` 才签发短期质量凭证；凭证绑定操作者、文件 SHA-256、配置版本和有效期，创建视觉任务时必须验证，`RETAKE`、缺失、过期、篡改或跨操作者凭证均拒绝。当前本地 Demo 的 `.env` 设置 `VISION_QUALITY_ENFORCE_RETAKE=false`，因此质量指标只做提示，任何可解码图片都可进入 OCR；格式错误、损坏文件仍会被 API 拒绝。Demo 凭证使用单进程内存密钥，服务重启会安全失效；正式多 worker 部署必须改为持久化签名密钥或数据库质量记录。

```powershell
uv run python scripts/hct202_quality_demo.py --iterations 50
```

数据按实体药盒、采集日期、设备和视频会话分组划分。发布至少报告每类指标、未知 SKU 转人工率、自动通过精确率、CPU/GPU 延迟、失败样例和旧类别退化，并支持 V1/V2 回滚。

## 本地实验引擎（EXPERIMENTAL_UNRELEASED）

`local_ocr.py` 与 `local_models.py` 提供家庭可信域内运行的四个本地引擎，全部默认降级、失败不阻塞链路、版本由制品自证：

| 引擎 | 角色 | 依赖（可选） | 不可用时 |
|---|---|---|---|
| `LocalPaddleOCR` | 文字主来源：全图 OCR 优先，YOLO 裁剪只补充非重复 token（隔离子进程 `_paddle_worker`） | `paddleocr`（`src/models/vision/ocr/paddleocr/ppocrv4-ch`，CPU） | 返回空列表，适配器记录降级 |
| `YoloBoxAssist` | 包装/裁剪辅助定位，不承担药品身份（隔离子进程 `_yolo_worker`） | `ultralytics` + `src/models/vision/yolo/.../weights/best.pt` | 返回空列表 |
| `LocalBarcodeDecoder` | 条码/二维码独立通道，GTIN 校验位规则判定 | `opencv-contrib` | 返回空列表 |
| `rule_fields.propose_fields` | 契约规定的规则/词典字段候选层：日期/批号/规格/厂家模式 + 逐字子 token 拆分 | 无（纯规则） | 不适用（确定性） |
| `QwenLoraFieldExtractor` | 已有候选的槽位归类，反幻觉过滤 | `transformers`/`peft`/`bitsandbytes` + 仓库外权重 | 返回空列表 |

进程隔离：paddle 与 torch 的原生 DLL 在同一 Windows 进程内两种加载顺序都会冲突，故 OCR 与 YOLO 均以短生命周期子进程运行、一次调用返回 JSON；子进程崩溃只降级为空证据，不影响主链路。

约束：裁剪 OCR 的 token 只能新增证据、不得替换或过滤全图 OCR 结果；规则候选只做逐字引用（子 token 必须是 OCR 原行的字面子串，继承原区域与置信度），生产日期不会被当作有效期；条码置信度由「解码成功 + 校验位」确定性规则给出，不采信模型自报；LLM 产出的字段值必须逐字存在于输入证据且引用已知证据 ID，否则本地即丢弃。全链路 CLI 见 `scripts/run_local_adapter.py`（`--ocr-json`/`--barcode-json` 可用外部引擎覆盖内建引擎，`--no-local-ocr`/`--no-local-barcode` 显式关闭）。所有结果必须经服务端融合与人工确认后才能写入健康事实。
