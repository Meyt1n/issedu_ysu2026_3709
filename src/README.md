# HomeCare Twin · 可展示运行目录

这是 HomeCare Twin 的精简运行仓库。运行所需的 API、AI、Web、共享组件、迁移脚本、本地模型配置和运行时数据都按用途放在清晰的目录中；项目说明和答辩材料保留在 `doc/`，不参与运行时导入。

## 目录地图

```text
src/
├─ api/                         FastAPI 后端与领域服务
├─ ai/                          AI、RAG、视觉识别与本地推理适配器
├─ web/                         Vue 前端（成员端与管理端）
├─ shared/voice/                前后端共享的语音类型与工具
├─ models/
│  ├─ face/                     YuNet/SFace 人脸视觉模型
│  ├─ llm/hct402-qlora-v5/      默认本地 LLM、Modelfile、模型说明
│  └─ vision/                   YOLO 包装检测与 PP-OCRv4 中文 OCR 模型
└─ runtime/
   ├─ data/                     主数据与上传文件（本机运行资产）
   ├─ database/                 SQLite 演示数据库（本机运行资产）
   └─ knowledge/                白名单、离线夹具与已批准知识
migrations/                     Alembic 数据库迁移
scripts/                        启动、停止、初始化、worker 与备份脚本
docker/                         API/Web 镜像与 Nginx 配置
```

## 默认运行方式

默认使用本机 Ollama，不调用云端 LLM。首次运行前确保已安装 `uv`、Node.js、Ollama，并在 PowerShell 中执行：

```powershell
uv sync --frozen
npm ci
uv run alembic upgrade head
ollama serve
.\scripts\register_local_llm_model.ps1
.\scripts\start.ps1 api
```

另开终端启动前端：

```powershell
.\scripts\start.ps1 web-member
```

默认模型名为 `hct402-qlora-v5`，模型文件为 `src/models/llm/hct402-qlora-v5/hct402-v5-merged-q8_0.gguf`。如果只需要演示全链路，也可以运行 `.\scripts\start-demo.ps1`；它会检查本地 Ollama 中是否已注册该模型。

视觉教学演示主数据可以用以下命令生成：

```powershell
uv run python scripts/setup_vision_demo.py
```

## 运行资产与 Git 边界

`src/runtime/database/*.sqlite3`、`src/runtime/data/`、`src/models/face/*.onnx`、`src/models/llm/**/*.gguf`、`src/models/vision/yolo/**/*.pt` 和 `src/models/vision/ocr/paddleocr/ppocrv4-ch/**` 已物理迁移到本目录，但被 `.gitignore` 排除。它们可能包含健康数据、上传文件或大体积模型权重，不应提交到 Git；仓库只提交结构、配置、Modelfile、哈希和模型说明。

`src/runtime/database/homecare-dev.sqlite3` 是当前本地演示数据库。正式部署前应使用空库执行迁移并导入经过审批的数据集。

## 运行安全

- `LLM_PROVIDER=local` 是默认值，云端配置为空；联网搜索默认关闭。
- 本项目为教学演示，不代表医疗器械或临床发布能力。
- 不要把真实健康数据、密钥、日志、缓存或模型权重加入提交。
