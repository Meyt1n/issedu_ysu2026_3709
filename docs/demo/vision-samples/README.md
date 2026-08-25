# 视觉闭环演示（中文 / 英文药盒）

本目录的两张药盒为 **AI 生成的合成教学样品**（无真实药品、无版权问题），
条码为可解码的真实 EAN-13 编码，与演示主数据快照对应：

- `demo-box-cn.jpg`：阿莫西林胶囊 0.25g×24粒（条码 6901234567892）
- `demo-box-en.jpg`：Ibuprofen Tablets 200mg × 20（条码 5012345678900）

权重、PaddleOCR 环境和家庭档案 **不进 Git**。按下面步骤可以在自己的机器上复刻「扫描 → 识别 → 复核 → 入档」，不要拷贝别人的盘符、数据库或真实健康数据。

## 别人需要自备的东西

| 组件 | 是否必须 | 说明 |
|---|---|---|
| 仓库代码 + 已启动的 API/Web | 必须 | 默认 API `http://127.0.0.1:8000` |
| 含 PaddleOCR 的独立 Python | 必须（识别） | 与项目 `.venv` **分开**；PaddlePaddle 与 PyTorch 不宜同进程 |
| 演示主数据快照 | 必须（对得上药名） | `uv run python scripts/setup_vision_demo.py` 生成本地文件 |
| YOLO `best.pt` | 可选 | 有则出现包装定位框；没有则仍有 OCR/条码框 |
| 已确认的家庭成员 | 必须（复核入档） | 在页面里自己建家庭/成员，不要导入他人 SQLite |

已验证过的 OCR 环境版本（自行安装，路径自己填）：

- Python 3.10/3.11 独立环境
- `paddleocr==2.7.3`、`paddlepaddle==2.6.2`、`opencv-python==4.10.*`、`numpy==1.26.*`

```powershell
# 自行填写：该解释器必须能 `import paddleocr`
$env:HCT_VISION_WORKER_PYTHON = "<你的 PaddleOCR 环境>\python.exe"
```

## 一次性准备

```powershell
# 1. 生成演示主数据（写入 data/master-data/demo-cn-en-v1.json，该目录不入库）
uv run python scripts/setup_vision_demo.py

# 2. API 与 worker 使用同一套签名密钥（必须与 .env 里 VISION_ADAPTER_SIGNING_KEY 一致）
$env:MASTER_DATA_APPROVED_VERSIONS = "demo-cn-en-v1"
$env:HCT_ADAPTER_SIGNING_KEY = "dev-only-change-me"
$env:HCT_MASTER_DATA_VERSION = "demo-cn-en-v1"
$env:HCT_OCR_LANG = "ch"    # 中文模型也可读英文包装
$env:NO_PROXY = "127.0.0.1,localhost"
```

启动 API 时同样带上 `MASTER_DATA_APPROVED_VERSIONS`。若使用 `.env`，把该行写进去后重启后端。
Docker Compose 部署同样支持：api 服务会透传 `.env` 中的 `MASTER_DATA_APPROVED_VERSIONS`
并以只读方式挂载 `./data/master-data`，先在宿主机生成快照再 `up` 即可。

> 诚实边界：`demo-cn-en-v1` 是 `INTERNAL_TEACHING_DEMO` 批准范围内的合成教学主数据
> （见 [HCT-201 教学演示批准范围](../../data/HCT-201-教学演示批准范围-V1.md)）。
> HCT-201 正式药品集仍为 UNRELEASED，`/api/v1/meta/capabilities` 中
> `hct201-formal-drug-set` 恒为 unavailable，直到正式门禁以真实证据通过。

可选 YOLO（仓库外权重，自行填写绝对路径）：

```powershell
$env:HCT_VISION_WEIGHTS = "<仓库外的 YOLO 权重>\best.pt"
$env:HCT_VISION_DEVICE = "cpu"
```

## 方式一（推荐）：常驻 worker，浏览器直接可用

网页「视觉扫描」只做质量门控、上传与建任务；识别由 worker 原子领取带租约的任务。

1. 打开页面，用一个 **你自己的 Actor ID** 进入（例如 `demo-parent`）。
2. 创建一个家庭和成员，记住这个 Actor ID。
3. 另开终端启动 worker（`--actors` 必须包含页面上填的身份）：

```powershell
$env:HCT_VISION_WORKER_PYTHON = "<你的 PaddleOCR 环境>\python.exe"
$env:HCT_MASTER_DATA_VERSION = "demo-cn-en-v1"
$env:HCT_OCR_LANG = "ch"
$env:HCT_ADAPTER_SIGNING_KEY = "dev-only-change-me"
$env:NO_PROXY = "127.0.0.1,localhost"

uv run python scripts/vision_worker.py `
  --api http://127.0.0.1:8000/api/v1 `
  --actors <页面上的 Actor ID> `
  --interval 5
```

4. 在「视觉扫描」上传 `docs/demo/vision-samples/demo-box-cn.jpg`（先过质量门控再创建任务）。
5. 等待 worker 日志出现接单；worker 会先调用 `POST /vision-tasks/claim`，推理结束前续租，PaddleOCR 单张大约 15–35 秒。
6. 「人工复核」出现候选后确认或修正；时间线 / 图谱 / 规则随之更新。

API 若改了端口，把 `--api` 改成你的地址，不要照抄他人的 `8001`。

## 方式二：单张手动跑

```powershell
$env:HCT_VISION_WORKER_PYTHON = "<你的 PaddleOCR 环境>\python.exe"
$env:HCT_MASTER_DATA_VERSION = "demo-cn-en-v1"
$env:HCT_OCR_LANG = "ch"
$env:HCT_ADAPTER_SIGNING_KEY = "dev-only-change-me"
$env:NO_PROXY = "127.0.0.1,localhost"

uv run python scripts/run_local_adapter.py `
  --image docs/demo/vision-samples/demo-box-cn.jpg `
  --api http://127.0.0.1:8000/api/v1 `
  --actor <页面上的 Actor ID> `
  --member-id <该家庭下的成员 ID> `
  --fuse
```

适配器提交证据后，服务端会融合并创建**待复核任务**（MATCHED 也必须人工确认）。随后在网页端：

1. 「视觉扫描」可展开识别详情：原图 + OCR/条码（及可选 YOLO）定位框。
2. 「人工复核」出现候选；确认后写入已确认健康事件。
3. 药盒不在主数据时，OCR 药名/规格仍会作为「主数据未收录」候选，可修正后入档或跳过。

## 常见失败

| 现象 | 原因 |
|---|---|
| 任务一直排队 | 未起 worker，或 `--actors` 与页面 Actor ID 不一致；可检查 worker 是否成功调用 claim 接口 |
| 任务反复处理中后变为 timeout | worker 多次崩溃或租约连续过期；确认本地模型环境后在页面点击重试 |
| `ADAPTER_RECEIPT_INVALID` | worker 与 API 的签名密钥不一致 |
| `NO_AUTHORISED_DOCUMENTS` / 复核空白 | 未批准 `demo-cn-en-v1`，或未选成员 |
| `QUALITY_GATE_REQUIRED` | 未先做质量检查，或凭证过期（API 重启后旧凭证失效） |
| 没有包装定位框 | 未设置 `HCT_VISION_WEIGHTS`，属预期 |

## 已知说明

- PaddleOCR 中文模型识别拉丁文会丢空格（`IbuprofenTablets`），演示主数据已登记别名。
- YOLO 只做包装/条码区域辅助，不决定药品身份。
- 单通道证据通常不会 `MATCHED`，进入人工复核是产品规范，不是缺陷。
