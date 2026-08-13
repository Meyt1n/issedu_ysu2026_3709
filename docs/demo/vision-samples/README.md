# 视觉闭环演示（中文 / 英文药盒）

本目录的两张药盒为 **AI 生成的合成教学样品**（无真实药品、无版权问题），
条码为可解码的真实 EAN-13 编码，与演示主数据快照对应：

- `demo-box-cn.jpg`：阿莫西林胶囊 0.25g×24粒（条码 6901234567892）
- `demo-box-en.jpg`：Ibuprofen Tablets 200mg × 20（条码 5012345678900）

## 一次性准备

```powershell
# 1. 生成演示主数据快照（写入 data/master-data/demo-cn-en-v1.json）
uv run python scripts/setup_vision_demo.py

# 2. 启动后端时批准该快照版本
$env:MASTER_DATA_APPROVED_VERSIONS = "demo-cn-en-v1"
uv run uvicorn app.main:app --app-dir src/api --port 8000
```

识别引擎运行在独立的 Python 环境（PaddlePaddle 与 PyTorch 不能同进程），
本机已验证的环境为 Anaconda `xa_code`（paddleocr 2.7.3 + paddle 2.6.2 +
opencv 4.10 + numpy 1.26）。

## 方式一（推荐）：常驻 worker，浏览器直接可用

网页端「视觉扫描」只负责质量门控、上传与建任务（排队）；识别由常驻
worker 轮询接单（`GET /vision-tasks?task_status=queued`，按身份隔离）：

```powershell
$env:HCT_VISION_WORKER_PYTHON = "C:\Users\32140\anaconda\envs\xa_code\python.exe"
$env:HCT_MASTER_DATA_VERSION  = "demo-cn-en-v1"
$env:HCT_OCR_LANG             = "ch"    # ch 模型可同时读中英文

uv run python scripts/vision_worker.py `
  --api http://127.0.0.1:8001/api/v1 `
  --actors parent-1,demo-parent --interval 5
```

`--actors` 填演示时使用的登录身份（逗号分隔）。之后在浏览器上传任意
药盒照片，任务会在数秒内被接单（PaddleOCR 单张约 15~35 秒），识别完成
后复核任务自动出现在「人工复核」页。

## 方式二：单张手动跑（拍照 → 质量门控 → OCR/条码 → 融合 → 复核任务）

```powershell
$env:HCT_VISION_WORKER_PYTHON = "C:\Users\32140\anaconda\envs\xa_code\python.exe"
$env:HCT_MASTER_DATA_VERSION  = "demo-cn-en-v1"
$env:HCT_OCR_LANG             = "ch"    # ch 模型可同时读中英文
$env:NO_PROXY                 = "127.0.0.1,localhost"

uv run python scripts/run_local_adapter.py `
  --image docs/demo/vision-samples/demo-box-cn.jpg `
  --api http://127.0.0.1:8000/api/v1 `
  --actor <家庭管理员身份> --member-id <成员ID> --fuse
```

适配器提交证据后，服务端会自动执行候选融合并创建**待复核任务**
（HCT-206 → HCT-207 桥接；MATCHED 也必须人工确认）。随后在网页端：

1. 「视觉扫描」页可展开任务的**识别详情**：原图 + OCR/条码定位框叠加、
   证据置信度、字段候选与发现事项；排队中的任务显示扫描动画；
2. 「人工复核」页出现候选（如 阿莫西林胶囊 0.63），卡片自带**原图缩略**，
   点开可查看完整定位框叠加；确认/修正后写入已确认健康事件，
   时间线、图谱与风险规则随之更新。
3. 药盒不在主数据时不会出现空复核：OCR 提取的药名/规格会作为
   「主数据未收录」候选带给复核员，可修正后入档或跳过。

## 已知说明

- PaddleOCR 中文模型识别拉丁文会丢空格（IbuprofenTablets），
  演示主数据已把常见变体登记为别名；
- YOLO 包装定位为可选通道（`HCT_VISION_WEIGHTS` 指向药盒检测权重后生效），
  当前演示的定位框来自 OCR 文本检测与条码定位；
- 单通道证据永远不会 MATCHED，本演示的设计结果即 REVIEW（信息不足，
  进入人工复核），这是产品规范的预期行为，不是缺陷。
