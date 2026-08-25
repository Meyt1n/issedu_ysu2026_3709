# HomeCare Twin 本地部署与 Demo 操作指南

> 家庭版默认不把健康数据发送到互联网。Demo 必须优先使用本地基础档/增强档；任何云端扩展都不属于默认演示路径。

## 1. 当前可执行状态

一期工程骨架可以运行健康检查、数据库迁移、家庭/成员/授权、不可变事件、兼容幂等与补偿、可恢复 outbox worker 和投影重放。仓库内还有视觉质量门控、OCR-first 证据、人工复核、本地知识检索和受约束助手接口；**权重、PaddleOCR 环境和微调模型不进 Git**，未配置时助手与识别应降级而不是假装完成。

正式药品固定集、模型发布、三档备份恢复演练和 R3 验收仍未关闭。不能把资源探针当作完整产品，也不能把质量门控或本机实验模型当成完整产品。总入口见根目录 [README](../README.md)。

### 1.1 干净环境标准复现路径

以下路径是 HCT-101 的基础档复现入口（工程骨架）。要复刻视觉识别与本地助手闭环，请改用功能分支 `feature/hct-local-model-adapter`，并阅读根目录 README 的「复刻本机视觉与助手闭环」。

`up` 默认使用 Compose profile `basic`，构建 API/Web/outbox worker/care-plan worker，等待 MySQL、API、两个 worker 和 Web 的健康检查，并在 API 容器启动时执行 Alembic 迁移；`down` 默认不删除 `mysql_data` 卷。所有业务服务都声明了 profile，**不指定 `basic`/`enhanced`/`dev` 时 Compose 不会启动任何容器**；启动脚本已默认补上 `--profile basic`。

Windows PowerShell：

```powershell
git clone https://github.com/Meyt1n/issedu_ysu2026_3709.git
cd issedu_ysu2026_3709
git switch master
Copy-Item .env.example .env
scripts/start.ps1 setup
scripts/start.ps1 up
scripts/start.ps1 health
scripts/start.ps1 down
```

Linux/macOS Bash：

```bash
git clone https://github.com/Meyt1n/issedu_ysu2026_3709.git
cd issedu_ysu2026_3709
git switch master
cp .env.example .env
chmod +x scripts/start.sh
./scripts/start.sh setup
./scripts/start.sh up
./scripts/start.sh health
./scripts/start.sh down
```

`health` 会同时检查 Compose 中 API、outbox worker、care-plan worker、Web、MySQL 的容器健康状态，并访问 API 与 Web 的 `/health`。默认浏览器入口为 `http://localhost:8080`，API 健康检查为 `http://localhost:8000/health`，OpenAPI 为 `http://localhost:8000/docs`。端口被占用时，在 `.env` 中修改 `API_PORT`、`WEB_PORT` 或 `MYSQL_PORT`，再重新执行 `up`。

增强档（额外启动 Ollama 容器）在启动前设置 `$env:COMPOSE_PROFILE='enhanced'`（Bash：`export COMPOSE_PROFILE=enhanced`）。容器内仍需自行拉取或创建模型；未配置 `OLLAMA_MODEL` 时助手保持结构化降级。

### 1.3 人脸识别本地模型（HCT-424/425）

人脸登录使用本地 OpenCV YuNet + SFace ONNX，**权重不进 Git**。首次部署请先准备模型：

```bash
uv run python scripts/ensure_face_models.py
```

然后在 `.env` 中确认：

- `FACE_MODEL_DIR=./models/face`
- `FACE_MODEL_AUTO_DOWNLOAD=true`（或改为 false 并手工拷贝 ONNX）
- `FACE_MATCH_THRESHOLD_SFACE` / `FACE_MATCH_MARGIN_SFACE`（见下方本机标定）

`/api/v1/meta/capabilities` 在模型就绪时会包含 `face-recognition-local`；未就绪时欢迎页会提示改用 PIN/密码。旧灰度 v1/v2 凭证仍可登录，管理员页会提示重新绑定升级。

#### 真实家庭摄像头阈值标定（必须本机完成）

默认阈值（`0.40` / margin `0.05`）来自公开样例，**不能代替你们家庭真实摄像头场景**。云端 Agent / CI **无法代采真人脸**，因此误拒/误识校准必须在维护者本机完成：

1. 用浏览器或摄像头为 3～6 位家庭成员采集 `enroll/` 与 `probe/` 照片（多种光线与轻微转头），目录示例：

```text
face-samples/
  grandpa/enroll/*.jpg
  grandpa/probe/*.jpg
  grandma/enroll/*.jpg
  grandma/probe/*.jpg
```

2. 本机运行校准（只读本地图片，不上传、不入库）：

```bash
uv run python scripts/calibrate_face_thresholds.py ./face-samples
```

3. 把脚本输出的推荐值写入 `.env` 后重启 API：

```env
FACE_MATCH_THRESHOLD_SFACE=...
FACE_MATCH_MARGIN_SFACE=...
```

未完成本机标定前，可将人脸登录视为“可用但未按家庭场景验收”；正式演示或 R3 前应完成上述步骤。

### 1.2 本地进程开发路径

需要调试 Vue/FastAPI 时可以不启动 Compose 的 API/Web，但仍必须先安装依赖并执行迁移。若 `.env` 里的 `DATABASE_URL` 指向 MySQL 而本机没有库，请改成 SQLite，例如 `$env:DATABASE_URL='sqlite+pysqlite:///./homecare-dev.sqlite3'`。

```powershell
scripts/start.ps1 setup
scripts/start.ps1 migrate
scripts/start.ps1 api
```

另开终端执行 `scripts/start.ps1 web`。Linux/macOS 将脚本名替换为 `scripts/start.sh`。本地进程路径不会自动启动 outbox worker；该路径的 `/api/v1/health/db` 使用本地 `DATABASE_URL` 检查数据库，不能代替 Compose 服务级 `health`。

带卷删除数据库前必须先完成备份演练；标准 `down` 不会删除卷。确需清空教学数据库时，必须由负责人单独执行 `docker compose down --volumes` 并记录影响。

## 2. 三档运行目标

| 档位 | 服务 | 适用环境 |
|---|---|---|
| 基础档 | Vue、FastAPI、outbox worker、care-plan worker、MySQL、规则、轻量 OCR | 低配置电脑；断网仍可管理档案、任务和历史证据；网络出口默认拒绝 |
| 增强档 | 基础档 + FAISS/Qdrant + Ollama 量化模型 | 建议 16 GB 以上内存；Compose profile `enhanced` 会多起 Ollama 容器，业务助手仍取决于本机是否已登记模型 |
| 研发档 | 增强档 + 数据标注、训练、评测和模型登记 | GPU 工作站或短时云 GPU；不得在家庭端自动训练 |

MySQL、Ollama、向量检索和文件服务默认仅监听本机/容器网络，不暴露公网。

outbox worker 默认每 2 秒处理最多 100 条消息，5 分钟前的 `PROCESSING` 锁视为中断并自动恢复；可通过 `.env` 的 `OUTBOX_POLL_SECONDS`、`OUTBOX_BATCH_SIZE` 和 `OUTBOX_STALE_SECONDS` 调整。维护者可在 OpenAPI 使用家庭 Owner 身份查询 `/api/v1/households/{id}/outbox` 或手工触发 `/outbox/dispatch`。停止 worker 不删除消息；恢复前不得手工修改健康事件。

care-plan worker（HCT-304/HCT-308）默认每 30 秒对显式授权的用药计划执行一次疗程结束、漏服升级和照护者通知评估，可通过 `.env` 的 `CARE_PLAN_POLL_SECONDS` 调整；worker 首个成功周期会写入就绪文件供容器探针使用。它只依据已确认的计划与授权数据产生 `care_escalated`/`caregiver_notified` 事件，不做任何医疗判断；失败时策略与 outbox worker 一致——单个 worker 不健康不会拖垮其它服务，`restart: unless-stopped` 会自动重启。本地进程调试可运行 `uv run python -m app.care_plan_worker --loop`（在 `src/api` 的 PYTHONPATH 下）。

## 3. HCT-003 资源探针

资源探针只使用合成灰度矩阵和固定技术握手，不读取或上传健康数据。先完成依赖安装：

```powershell
uv sync
uv run pytest tests/unit/test_hct003_resource_probes.py
```

运行视觉质量探针：

```powershell
uv run python scripts/hct003_probe.py vision --strict
```

运行 MySQL 基础档。若宿主机 `3306` 已占用，可使用 `3307` 作为本机临时映射，容器内端口仍为 `3306`：

```powershell
$env:MYSQL_PORT='3307'
$env:MYSQL_DATABASE='homecare'
$env:MYSQL_USER='homecare'
$env:MYSQL_PASSWORD='change-me'
$env:MYSQL_ROOT_PASSWORD='change-me-root'
docker compose up -d --wait --wait-timeout 60 db
$env:DATABASE_URL = 'mysql+pymysql://' + $env:MYSQL_USER + ':' + $env:MYSQL_PASSWORD + '@localhost:' + $env:MYSQL_PORT + '/' + $env:MYSQL_DATABASE + '?charset=utf8mb4'
uv run alembic upgrade head
uv run python scripts/hct003_probe.py mysql --database-url $env:DATABASE_URL --strict
```

运行增强档 Ollama。模型必须已经安装在本机，探针只允许回环地址：

```powershell
ollama list
uv run python scripts/hct003_probe.py ollama --model qwen2.5:7b --strict --timeout 120
```

服务未启动或模型不存在时，不要改成云端地址；省略 `--strict` 会返回 `degraded` 和 `structured_core_only`，基础事实/规则链保持可用。模型体积、显存、耗时和失败模式的实际证据见 [HCT-003 评审记录](reviews/HCT-003-资源原型与技术选型评审记录.md)。

## 4. 配置契约

示例配置必须只包含占位值，至少覆盖：数据库连接、JWT 密钥路径、文件加密密钥路径、上传限制、原图保留期、视觉/OCR 模型版本、Ollama 地址与模型名、向量索引版本、规则集版本、知识库版本和天气适配器城市编码。

天气请求不得上传姓名、病史、药品或详细住址。生产密钥不能写入仓库、镜像或日志。

### 4.1 HCT-202 合成质量 Demo

以下命令只在内存生成无敏感信息的清晰、模糊、暗光、过曝和尺寸不足样例，用于验证质量 Schema、重拍提示和单图性能，不代表真实药盒阈值已校准：

```powershell
uv sync --frozen
uv run python scripts/hct202_quality_demo.py --iterations 50
```

启动 API 后，直接把当前用户选择的图片提交给质量接口；接口不会通过 `file_id` 读取共享文件区：

```powershell
curl.exe -X POST http://localhost:8000/api/v1/vision-quality/check `
  -H "X-Actor-ID: demo-owner" `
  -F "media_type=image" `
  -F "file=@C:\path\to\demo.png;type=image/png"
```

返回 `RETAKE` 或 `allow_downstream=false` 时，Demo 必须展示重拍原因，不得继续自动确认，也不会签发 `quality_receipt`。只有 `PASS` 的短期凭证才能与同一文件 SHA-256、同一操作者和同一配置版本一起创建 `/api/v1/vision-tasks`；缺失、跨用户、过期、篡改或文件不一致均返回冲突。接口响应不包含图片像素、原文件名或本机路径；视频可使用 `media_type=video`、`sample_interval_ms` 和 `max_selected_frames` 表单字段。

当前凭证使用 Demo 单进程内存密钥，默认 10 分钟有效；API 重启后旧凭证失效。正式多 worker 部署必须使用持久化签名密钥或数据库质量记录，不得通过关闭凭证检查解决失效问题。

Web Demo 可直接演示同一流程：

```powershell
.\scripts\start.ps1 api
# 另开一个终端
.\scripts\start.ps1 web
```

打开 `http://127.0.0.1:5173`，填写开发身份后，在“先检查图片，再进入识别”区域选择 JPEG/PNG。页面只在浏览器内生成预览；`RETAKE` 明确停止，`PASS` 后由用户点击创建本地 OCR 任务。页面会核对质量检查与持久化上传的 SHA-256，并且不会显示服务端路径、文件摘要或质量凭证。切换身份或替换图片会使旧结果失效。

Windows 本地开发代理固定使用 `127.0.0.1`，避免 `localhost` 解析为 IPv6 而 API 仅监听 IPv4。API 启动脚本和容器必须同时包含 `src/api` 与 `src` 的 Python 导入路径，否则质量模块无法加载。

## 5. 后续必须补齐

- 正式 Ollama 业务工具、输出 Schema、模型登记、GPU/CPU 和模型权重哈希；
- 迁移回滚、备份恢复和删除传播的演练记录；
- 基础档和增强档的完整功能启动、停止与健康检查证据；
- Web、OpenAPI、业务大屏和模型大屏的真实地址；
- 全链路从全新克隆开始的复现记录、耗时和最低硬件，见[HCT-101 干净环境复现记录](reviews/HCT-101-工程骨架干净环境复现记录.md)；HCT-003 仅覆盖资源探针；
- 常见故障：数据库未就绪、模型缺失、OCR 超时、向量索引不匹配、磁盘不足。

## 6. 连续 Demo 剧本

演示助手「朗读回答」或随身版长辈「语音播报」前，先按 [中文语音包与听感准备说明](demo/中文语音包与听感准备说明.md) 确认演示机已安装 Natural 类中文 TTS；仅有机械默认包时须在演示话术中诚实说明听感受限。

1. 上传新药短视频或主动拍照，OpenCV 选择质量合格的证据帧，先运行全图 OCR；YOLO 仅辅助检测包装和条码区域。
2. 条码由专用解码器读取，OCR 与条码或主数据冲突时系统返回 `CONFLICT`，不自动入库；页面同时展示原始 OCR 区域、条码证据、包装特征、本地主数据和各阶段模型版本。
3. 用户复核并修正错误候选，页面展示 before/after、原因和训练同意未默认勾选。
4. 用户复核后创建 `MEDICINE_ADDED` 事件，关系投影新增成员—药品—成分关系。
5. 规则命中一条有限相互作用资料，风险卡展开数据库事实、规则版本、说明书和确认状态。
6. 本地 LLM 只基于这些证据解释，不能给出停药、换药或剂量建议。
7. 用户在既有医嘱安全时间窗内建立提醒；连续未确认触发授权照护者升级。
8. 同类普通告警被合并，天气只生成一次低风险行动卡。
9. 为子女创建“只看任务摘要、不可看报告正文”的授权，验证字段过滤和到期时间展示。
10. 用户询问“为什么最近提醒增加”，系统从事件时间线解释原因。
11. 人工纠错进入困难样本池，管理员展示 V1/V2 固定集对比和回滚入口。
12. 页面不存在买药、问诊、广告或佣金导流入口；无证据请求必须拒答。

## 7. Demo 验收证据

- 干净环境部署记录及服务版本；
- 正常、`UNKNOWN`、`CONFLICT`、无证据、越权、模型离线和规则升级场景录屏；
- 断网状态仍可查看本地事实、规则和任务；天气仅展示按城市/区县编码的受控出口；
- 数据卡、模型卡、规则/文档版本及固定评估集结果；
- 敏感数据删除、授权撤回、备份恢复和模型回滚记录；
- 页面明确显示“教学演示，不替代医疗诊断”。
