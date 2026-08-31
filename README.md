# 家健镜 HomeCare Twin

本地优先的家庭居家照护教学系统：把药品、过敏、指标和计划的变化写成不可覆盖的健康事件，用多证据视觉录入、确定性规则和受约束本地大模型，帮助家庭看清「发生了什么、依据是什么、下一步谁确认」。

> **产品硬承诺：** 健康数据默认不出网；药盒识别必须多渠道核对且支持人工修正；子女只能看到被精细授权的信息；提醒按等级和预算控制；AI 只能基于完整证据解释，不做诊断、处方或自主用药判断；不提供买药、问诊和广告导流。

> **使用边界：教学演示，不用于诊断或治疗。** 紧急情况请联系医务人员或当地急救服务。

## 当前状态

一期工程骨架、家庭/成员/授权、不可变事件、状态投影、规则与风险、视觉质量门控、OCR-first 证据、人工复核、本地知识检索和受约束助手接口已经进入本仓库，并有自动测试。

**完整 P0 业务仍未关闭：** 正式药品固定集、模型发布、三档部署演练和 R3 验收尚未完成。进度以[需求追踪矩阵](docs/vibe-coding/12-需求追踪矩阵.md)及可复现证据为准，不以 README、截图或本地实验冒充已交付。当前核心能力的机器验收入口见 [P0 核心能力验收包](docs/acceptance/HCT-P0-核心能力验收方案.md)。

产品界面是 `src/web` 的 Vue 应用（多套可切换主题，含「青黛映蓝」）。`src/web/react` 是风格与教学页面来源，不是第二套运行时。

## 快速开始：如何部署

需要 [Git](https://git-scm.com/)、[uv](https://docs.astral.sh/uv/)（Python 3.11）、[Node.js 22+](https://nodejs.org/) 和 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（Compose 路径）。Windows 用 PowerShell，Linux/macOS 把 `scripts/start.ps1` 换成 `scripts/start.sh`。

更细的端口、探针、质量 Demo 和故障说明见[本地部署与 Demo 操作指南](docs/本地部署与Demo操作指南.md)。干净环境复现证据见 [HCT-101 记录](docs/reviews/HCT-101-工程骨架干净环境复现记录.md)。部署起来后想按功能逐项「点亮」，请看下方[功能与 API 启动指南（按功能开启）](#功能与-api-启动指南按功能开启)；**本机已有 Ollama / PaddleOCR / YOLO 时，优先看 [路径 C：本机全功能演示栈](#路径-c本机全功能演示栈windowsstart-demops1)**。

### 路径 A：Docker Compose 基础档（推荐干净机器）

基础档启动 MySQL、FastAPI、outbox worker、care-plan worker（HCT-308 漏服升级/照护通知）和 Nginx 托管的 Vue 前端。Ollama 默认不启动，助手接口返回结构化降级，档案/事件/规则仍可用。

```powershell
git clone https://github.com/Meyt1n/issedu_ysu2026_3709.git
cd issedu_ysu2026_3709
# 所有已交付能力（含视觉质量门控、人工复核、助手接口）均以 master 为准
Copy-Item .env.example .env
# 把 .env 里的 change-me 密码换成自己的本地口令，不要提交该文件

scripts/start.ps1 setup
scripts/start.ps1 up
scripts/start.ps1 health
```

| 入口 | 地址 |
|---|---|
| 成员前台（家人正式账号密码） | http://localhost:8080 |
| 管理后台（管理员正式账号密码） | http://localhost:8081 |
| API 健康检查 | http://localhost:8000/health |
| OpenAPI | http://localhost:8000/docs |

前台/后台是同一容器、同一构建产物的两个监听端口（HCT-453），共用同一个 API、正式 Bearer 会话和同一授权真相；账号与入口不匹配时会被登出并指引到另一入口。两个登录页保留成员/管理员品牌差异，但不提供开发 Actor ID；成员前台恢复正式账号密码、已配置 PIN/人脸和注册入口，管理员仍以正式账号密码为主（HCT-498 修订）。

首次本地演示先运行 `uv run python scripts/seed_formal_demo_health.py`，再用正式演示账号 `demo-parent` 登录；脚本的教学默认密码为 `DemoOnly-ChangeMe!`，仅限本机虚构数据演示，共享/正式部署必须改为独立强密码。`ALLOW_DEV_ACTOR_HEADER` 缺省为 `false`，只有隔离 API 测试或诊断才可显式临时开启，Web 永不暴露该入口。

端口冲突时改 `.env` 的 `API_PORT`、`WEB_PORT`、`ADMIN_WEB_PORT`、`MYSQL_PORT` 后重新 `up`。

```powershell
scripts/start.ps1 down          # 停服务，默认保留 mysql_data 卷
```

清空教学库必须由负责人显式执行 `docker compose --profile basic down --volumes` 并记录影响；标准 `down` 不会删卷。

增强档（额外启动本机 Ollama 容器）在启动前设置：

```powershell
$env:COMPOSE_PROFILE = "enhanced"
scripts/start.ps1 up
```

容器内的 Ollama 仍需自行 `ollama pull` / `ollama create` 模型；未配置 `OLLAMA_MODEL` 时助手保持降级。HCT-408 三档备份恢复：可弃置 FILE_ROOT 备份→破坏→恢复已有自动演练（见 [演练记录](docs/reviews/HCT-408-可弃置备份恢复演练记录.md)）；Compose 实跑 MySQL DROP/IMPORT 与独立 R3 仍未完成，不能把增强档当成已验收交付。

### 路径 B：本地进程（调试 Vue / FastAPI）

适合改代码。不自动启动 outbox worker。默认 API 配置是 SQLite `./homecare-dev.sqlite3`；一旦存在 `.env`（`setup`/`up` 会从示例复制），`DATABASE_URL` 会指向 Compose 的 MySQL——没有 MySQL 时请改成 SQLite，或先只起数据库。

```powershell
scripts/start.ps1 setup
$env:DATABASE_URL = "sqlite+pysqlite:///./homecare-dev.sqlite3"
scripts/start.ps1 migrate

# 终端 1
scripts/start.ps1 api

# 终端 2（成员前台，或调试用单入口 scripts/start.ps1 web）
scripts/start.ps1 web-member

# 终端 3（可选：管理后台入口）
scripts/start.ps1 web-admin
```

| 入口 | 地址 |
|---|---|
| 成员前台（`web-member`） | http://127.0.0.1:5173 |
| 管理后台（`web-admin`） | http://127.0.0.1:5174 |
| 调试单入口（`web`，按账号角色进门户） | http://127.0.0.1:5173 |
| API | http://127.0.0.1:8000 |

两个前端进程共用同一个 API（HCT-453）。等价命令：`npm run dev:web:member` / `npm run dev:web:admin`，或 `HCT_WEB_PORT=5174 VITE_PORTAL_MODE=admin npm run dev:web`。

#### 正确进入「成员前台」（HCT-456）

1. 终端 1：`scripts/start.ps1 api`（或 `scripts/start.sh api`）
2. 终端 2：`scripts/start.ps1 web-member`（**不要**只用 `web`；`web` 是调试单入口）
3. 浏览器打开 http://127.0.0.1:5173（Compose 则用 http://localhost:8080）
4. 用已预置的**家庭成员正式账号密码**登录（演示账号如 `grandma-demo` / `grandpa-demo`，密码由受控开户脚本或管理员设置）
5. **不要**用家庭管理员（创建家庭的人，如 `demo-parent`）进成员前台——会被入口锁登出并指引去管理后台 5174/8081

本机代理固定走 `127.0.0.1`，避免 `localhost` 解析到 IPv6。多人联调可设 `HCT_API_PROXY`（后端）、`HCT_WEB_PORT`（前台端口）和 `HCT_ADMIN_WEB_PORT`（后台端口）。

### 路径 C：本机全功能演示栈（Windows，`start-demo.ps1`）

适合**已经自备本机 Ollama 模型、PaddleOCR 环境、YOLO 权重**的研发/演示机：一条脚本拉起 MySQL + API + outbox/care-plan worker + 成员前台 + 视觉 worker，再另开管理后台。权重与 OCR 环境**不进 Git**，路径需按本机填写。

#### 前置条件

| 组件 | 是否必须 | 说明 |
|---|---|---|
| Docker Desktop | 必须 | 仅用于 MySQL（`scripts/start-demo.ps1` 会 `docker compose up db`） |
| [uv](https://docs.astral.sh/uv/) + Node.js 22+ | 必须 | 脚本内会跑迁移与 `npm run dev:web` |
| 本机 Ollama + 已登记模型 | 必须（助手真实生成） | 例：`ollama list` 能看到 `hct402-qlora-v5` 或 `qwen3:4b` |
| 独立 PaddleOCR Python | 必须（视觉推理） | 与项目 `.venv` **分开**；须能 `import paddleocr` |
| YOLO `best.pt` | 推荐 | 仓库外绝对路径；没有则 OCR/条码仍可用，capabilities 中 YOLO 相关能力降级 |
| `.env` | 必须 | 从 `.env.example` 复制后按下方「全功能 `.env` 模板」补全 |

#### 一次性准备

```powershell
cd issedu_ysu2026_3709
Copy-Item .env.example .env    # 若已有 .env，对照模板补项即可

scripts/start.ps1 setup
uv run python scripts/setup_vision_demo.py      # 教学主数据 demo-cn-en-v1
uv run python scripts/ensure_face_models.py     # YuNet + SFace（历史人脸凭证实验能力，不作为 Web 登录入口）
```

确认 Docker Desktop 已运行。若本机 **3307** 被其他容器占用（常见于其它 worktree 的 MySQL），先释放端口或改 `.env` 的 `MYSQL_PORT` 与 `DATABASE_URL` 保持一致。

#### 全功能 `.env` 模板（本地演示推荐）

下列片段写入根目录 `.env`（密码仍用 `change-me` 即可，**勿提交**）。改任何项后须**重启 API** 才生效。

```dotenv
# ── 基础 / 双入口（HCT-453）──
ALLOW_DEV_ACTOR_HEADER=false
CORS_ORIGINS=http://localhost:5173,http://localhost:5174,http://localhost:8080,http://localhost:8081
MYSQL_PORT=3307
DATABASE_URL=mysql+pymysql://homecare:change-me@127.0.0.1:3307/homecare?charset=utf8mb4

# ── 视觉推理 vision-inference（API 声明 + worker 实际执行）──
# API：OCR_VERSION 非 unavailable 时 capabilities 会出现 vision-inference
OCR_VERSION=paddleocr-2.7.3-ppocrv4-ch
VISION_MODEL_VERSION=hct-yolo11n-box-assist-experimental-v1.2
VISION_ADAPTER_SIGNING_KEY=dev-only-change-me
VISION_ADAPTER_ALLOWLIST=homecare-local-vision
MASTER_DATA_APPROVED_VERSIONS=demo-cn-en-v1
MASTER_DATA_ROOT=./data/master-data

# ── 本机 Ollama + 开放演示（HCT-451）──
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=hct402-qlora-v5
OLLAMA_TIMEOUT_SECONDS=120
AGENT_OPEN_CHAT=true
AGENT_OPEN_MAX_TOKENS=4096

# ── 联网搜索 external-web（二选一，见下节）──
AGENT_WEB_SEARCH_ENABLED=true
# 路线 1：课堂夹具（不出网，capabilities 无 external-web）
# AGENT_WEB_SEARCH_PROVIDER=fixture
# 路线 2：真实白名单出口（capabilities 出现 external-web）
AGENT_WEB_SEARCH_PROVIDER=duckduckgo_html
AGENT_WEB_SEARCH_URL=https://html.duckduckgo.com/html/
AGENT_WEB_SEARCH_ALLOWED_DOMAINS=html.duckduckgo.com

# ── 天气 / 健康资讯 ──
WEATHER_ADAPTER=enabled
WEATHER_PROVIDER=uapis
WEATHER_API_URL=https://uapis.cn/api/v1/misc/weather
WEATHER_DEFAULT_CITY_CODE=130600
WEATHER_LOCATION_WHITELIST=130600,130629
EGRESS_WEATHER_WHITELIST=uapis.cn
HEALTH_NEWS_ADAPTER=enabled
HEALTH_NEWS_ALLOWED_DOMAINS=www.who.int,www.nhc.gov.cn,www.chinacdc.cn

# ── 历史人脸凭证实验能力（不作为 Web 登录入口）──
FACE_MODEL_DIR=./models/face
FACE_MODEL_AUTO_DOWNLOAD=true
BIOMETRIC_ENCRYPTION_KEY=dev-only-biometric-key-change-me
```

Worker 侧环境变量在**启动终端**设置（与 API 的 `VISION_ADAPTER_SIGNING_KEY` 必须一致）：

```powershell
$env:HCT_VISION_WEIGHTS = "<仓库外 YOLO 权重>\best.pt"
$env:HCT_VISION_WORKER_PYTHON = "<PaddleOCR 环境>\python.exe"
$env:HCT_VISION_DEVICE = "0"          # 无 GPU 可改为 cpu
$env:HCT_VISION_CONF = "0.25"
$env:HCT_ADAPTER_SIGNING_KEY = "dev-only-change-me"
$env:HCT_MASTER_DATA_VERSION = "demo-cn-en-v1"
$env:HCT_OCR_LANG = "ch"
$env:NO_PROXY = "127.0.0.1,localhost"
```

#### 一键启动（成员前台 + API + Worker）

```powershell
# 1. 停止上一轮（保留 MySQL 数据卷）
.\scripts\stop-demo.ps1 -KeepDatabase
Start-Sleep -Seconds 3

# 2. 设置本机视觉 worker 环境（路径改成你的）
$env:HCT_VISION_WEIGHTS = "<仓库外 YOLO 权重>\best.pt"
$env:HCT_VISION_WORKER_PYTHON = "<PaddleOCR 环境>\python.exe"
$env:HCT_VISION_DEVICE = "0"
$env:HCT_VISION_CONF = "0.25"
$env:HCT_ADAPTER_SIGNING_KEY = "dev-only-change-me"
$env:HCT_MASTER_DATA_VERSION = "demo-cn-en-v1"
$env:HCT_OCR_LANG = "ch"

# 3. 启动：Ollama（若未运行）+ MySQL + API + outbox + care-plan + 5173 + vision worker
.\scripts\start-demo.ps1 `
  -Model "hct402-qlora-v5" `
  -MysqlPort 3307 `
  -ApiPort 8000 `
  -WebPort 5173 `
  -ActorId "demo-parent,parent-1" `
  -VisionWorkerPython $env:HCT_VISION_WORKER_PYTHON `
  -IncludeVisionWorker `
  -Visible
```

成功时终端会打印：

```text
HomeCare Twin Demo is running.
Web: http://127.0.0.1:5173
API: http://127.0.0.1:8000/docs
Ollama: http://127.0.0.1:11434
```

#### 管理后台（5174，需另开终端）

`start-demo.ps1` 默认只起成员前台。管理后台需**第二个终端**：

```powershell
cd issedu_ysu2026_3709
scripts/start.ps1 web-admin
# 等价：npm run dev:web:admin
```

| 入口 | 地址 | 适用身份 |
|---|---|---|
| 成员前台 | http://127.0.0.1:5173 | 家庭成员：正式账号密码 |
| 管理后台 | http://127.0.0.1:5174 | 家庭管理员：正式账号密码（如 `demo-parent`） |
| API | http://127.0.0.1:8000/docs | — |

#### 停止

```powershell
.\scripts\stop-demo.ps1 -KeepDatabase   # 保留 MySQL；Ollama 模型不删
# 手动关闭 5174 的 npm 窗口（若开了 web-admin）
```

#### 验证「全部点亮」

```powershell
curl.exe http://127.0.0.1:8000/api/v1/meta/capabilities
$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/login `
  -ContentType 'application/json' `
  -Body (@{ actor_id = 'demo-parent'; password = 'DemoOnly-ChangeMe!' } | ConvertTo-Json)
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/assistant/agents `
  -Headers @{ Authorization = "Bearer $($login.session_token)" }
```

全功能配置下，`available` 应包含（节选）：

| capability | 含义 | 关键条件 |
|---|---|---|
| `vision-inference` | OCR/条码/YOLO 推理已配置 | `.env` 中 `OCR_VERSION` ≠ `unavailable`；且 vision worker 在跑 |
| `external-web` | 真实联网搜索出口就绪 | `AGENT_WEB_SEARCH_PROVIDER=duckduckgo_html` 且白名单通过；**不是** `fixture` |
| `master-data-teaching-demo` | 教学主数据已批准 | `MASTER_DATA_APPROVED_VERSIONS=demo-cn-en-v1` + 已跑 `setup_vision_demo.py` |
| `face-recognition-local` | 人脸模型就绪 | `ensure_face_models.py` 成功 |
| `llm` | 本地 Ollama 可用 | `OLLAMA_MODEL` 指向本机已安装模型 |

助手目录接口期望（真实联网时）：

- `open_chat`: `true`，`open_max_tokens`: `4096`
- `web_search_provider`: `duckduckgo_html`，`web_search_offline_fixture`: `false`
- 页面仍需每次勾选「补充联网参考」（双重开关）

视觉 worker 日志（`tmp/demo-artifacts/demo-logs/vision-worker.out.log`）应类似：

```text
engines ready: {"yolo": true, "ocr": true, "barcode": true, "llm": false}
watching queued tasks ... api=http://127.0.0.1:8000/api/v1
```

上传合成药盒见 [`docs/demo/vision-samples/`](docs/demo/vision-samples/README.md)。

#### 分项启动说明（对照表）

| 功能 | `.env` / 环境 | 启动动作 | 页面验证 |
|---|---|---|---|
| **基础档 + Worker** | `DATABASE_URL` 指向 MySQL | `start-demo.ps1`（含 outbox/care-plan） | `/health`、`/api/v1/health/db` |
| **vision-inference** | 上表 OCR/VISION + worker 环境变量 | `-IncludeVisionWorker` 或手动 `scripts/vision_worker.py` | capabilities 含 `vision-inference`；扫描页上传药盒后进四态/复核 |
| **external-web（真实）** | `duckduckgo_html` + 白名单域名 | 重启 API | capabilities 含 `external-web`；助手勾选联网，徽标为「真实联网 · 白名单出口」 |
| **external-web（夹具）** | `AGENT_WEB_SEARCH_PROVIDER=fixture` | 重启 API | `web_search_ready=true` 但 capabilities **无** `external-web`；徽标「教学夹具 · 不出网」 |
| **开放演示助手** | `AGENT_OPEN_CHAT=true` | 重启 API | agents 中 `open_chat=true`；可问「今天几号」 |
| **本地 LLM** | `OLLAMA_MODEL=<本机模型名>` | 本机 `ollama serve` + 重启 API | 助手真实回答，非结构化降级 |
| **人脸凭证实验能力（非 Web 登录）** | `FACE_MODEL_*` | `ensure_face_models.py` | capabilities 含 `face-recognition-local` |
| **天气行动卡** | `WEATHER_ADAPTER=enabled` + 白名单 | 重启 API | `GET /api/v1/weather/action-cards?city_code=130600` |
| **健康资讯出网** | `HEALTH_NEWS_ADAPTER=enabled` + 域名白名单 | 重启 API | `GET /api/v1/health-news` → `status=ok` |
| **知识爬虫** | `KNOWLEDGE_ADMIN_ACTORS`（可选） | 无需额外进程 | 知识文档页「一键教学闭环」；详见[联网搜索与知识库刷新启用指南](docs/demo/联网搜索与知识库刷新启用指南.md) |

#### 常见排障（路径 C）

| 现象 | 原因 | 处理 |
|---|---|---|
| MySQL 启动失败 `port 3307 already allocated` | 其他 Docker 项目占用 3307 | `docker ps` 找到占用容器并 `docker stop …`，或改 `.env` 的 `MYSQL_PORT` |
| capabilities 仍无 `vision-inference` | `OCR_VERSION=unavailable` 或 API 未重启 | 改 `.env` 后**重启 API 进程**（不是只改 worker） |
| capabilities 仍无 `external-web` | 仍为 `fixture` 或白名单未过 | 改用 `duckduckgo_html` 并设 `AGENT_WEB_SEARCH_ALLOWED_DOMAINS=html.duckduckgo.com` |
| 视觉任务一直 queued | worker 未跑 / Actor 不匹配 / 签名密钥不一致 | 确认 worker 日志里 `api=…8000`；`--actors` 含页面 Actor；`HCT_ADAPTER_SIGNING_KEY` = `VISION_ADAPTER_SIGNING_KEY` |
| worker 日志 `yolo: false` | 未设 `HCT_VISION_WEIGHTS` 或路径错误 | 启动前 export 权重绝对路径 |
| 助手仍像「夹具联网」 | API 未加载新 `.env` | 结束占用 8000 的进程后重启 API |
| 改 `.env` 不生效 | Compose/uvicorn 进程未重启 | `stop-demo.ps1` 后再 `start-demo.ps1`，或 kill 8000 端口后重启 API |

更细的视觉 / Ollama / 联网分步说明：

- 视觉闭环 → [视觉演示说明](docs/demo/vision-samples/README.md)
- 本地模型 → [本地大模型闭环](docs/demo/local-llm-v5.md)
- 联网与知识库 → [联网搜索与知识库刷新启用指南](docs/demo/联网搜索与知识库刷新启用指南.md)
- 开放演示助手 → [助手开放演示模式](docs/助手开放演示模式.md)

### 可选：复刻本机视觉与助手闭环

权重、PaddleOCR 环境和微调 GGUF **不进 Git**，别人必须在自己机器上准备，不要拷贝他人盘符或 SQLite。没有它们时，质量门控、建任务、人工复核和助手降级仍然可用。

要接近「扫合成药盒 → 复核入档 → 助手按事实回答」：

1. 用上面的路径 B 或 Compose 起 API/Web（默认端口 **8000 / 5173 或 8080**）。
2. 按 [视觉演示说明](docs/demo/vision-samples/README.md) 自备 PaddleOCR 环境、生成 `demo-cn-en-v1`、启动 `scripts/vision_worker.py`，上传本目录合成药盒。
3. 按 [本地大模型闭环](docs/demo/local-llm-v5.md) 在仓库外准备 Ollama 模型，设置 `OLLAMA_MODEL` 后重启 API；先在自己建的成员上确认一条用药再提问。
4. 若演示助手「朗读回答」或随身版长辈播报：先按 [中文语音包与听感准备说明](docs/demo/中文语音包与听感准备说明.md) 在本机安装 Natural 类中文 TTS；仓库不附带语音包，仅有机械默认音色时听感改善有限。

`VISION_ADAPTER_SIGNING_KEY` 必须与 worker 的 `HCT_ADAPTER_SIGNING_KEY` 相同（示例均为 `dev-only-change-me`）。v5 尚未完成正式评估，输出只用于教学演示。

### 可选：启用联网搜索与刷新知识库

两项能力默认关闭/受限。**按步骤启用请看专文：**

→ [联网搜索与知识库刷新启用指南](docs/demo/联网搜索与知识库刷新启用指南.md)

（环境说明亦可对照[本地部署与 Demo 操作指南 §4.2/§4.3](docs/本地部署与Demo操作指南.md)。）

**最短路径（课堂演示）：**

1. `.env` 写入并重启 API：

```dotenv
AGENT_WEB_SEARCH_ENABLED=true
AGENT_WEB_SEARCH_PROVIDER=fixture
```

2. 网页 Actor 填 `demo-parent` → 助手页勾选「补充联网参考」→ 提问。
3. 同一身份打开「知识文档」→「一键教学闭环：抓取 → 批准 → 晋升」→ 按页面提示做 dry-run 入库。

外部结果只作为「外部参考（非本地审核证据）」；爬虫**永不 auto_ingest**。

### 提交前检查

```powershell
scripts/start.ps1 check
```

等价于 Ruff、pytest、前端类型检查/构建和 Compose 配置校验。无法运行的检查要在 PR 里如实说明。

## 功能与 API 启动指南（按功能开启）

本节教新用户按功能域把系统「点亮」：先一键起基础档，再按需要开启可选能力。命令以 Windows PowerShell 为例，Linux/macOS 把 `scripts/start.ps1` 换成 `scripts/start.sh`（`$env:X='y'` 换成 `export X=y`）。每一项都以 master 上真实可运行代码为准；细节和排障见[本地部署与 Demo 操作指南](docs/本地部署与Demo操作指南.md)。

### 第 0 步：一键起基础档并确认能力清单

```powershell
Copy-Item .env.example .env      # Linux/macOS: cp .env.example .env
scripts/start.ps1 setup
scripts/start.ps1 up             # MySQL + API + outbox worker + care-plan worker + Web
scripts/start.ps1 health
curl http://localhost:8000/api/v1/meta/capabilities
```

`/api/v1/meta/capabilities` 是唯一的能力事实接口，诚实区分「可用 / 不可用」。**默认 `.env.example`（Compose 基础档）** 下：

- **`available`（基础档默认点亮）**：`manual-health-event`、`household-member`、`field-authorization`、`audit-outbox`、`event-compensation-replay`、`outbox-recovery-worker`、`review-task`、`vision-task`、`vision-task-video`、`knowledge-store`、`local-assistant`、`llm`、`risk-acknowledgement`；
- **`unavailable`（需额外准备或诚实关闭）**：`face-recognition-local`（未准备人脸模型）、`master-data-teaching-demo`（未批准教学主数据）、`vision-inference`（`OCR_VERSION=unavailable`）、`llm-cloud`、`external-web`（联网仍为 fixture 或未开白名单），以及**恒为不可用**的 `hct201-formal-drug-set`（正式药品固定集仍 UNRELEASED，属 fail-closed 诚实声明，不是故障）。

按 [路径 C：本机全功能演示栈](#路径-c本机全功能演示栈windowsstart-demops1) 配齐 `.env` 并启动 vision worker 后，`vision-inference`、`external-web`（真实 DuckDuckGo）、`face-recognition-local`、`master-data-teaching-demo` 等会进入 `available`。

页面只提供正式账号密码登录；登录成功后所有业务请求使用短期 Bearer 会话，401 或到期会清空页面内的家庭、成员和健康上下文。账号通过受控 API/脚本预置，不在登录页自助注册。开发身份头默认关闭，且正式 Web 不提供开启入口。

### 基础档默认可用（不需要额外配置）

| 功能 | 页面入口 | 如何验证 |
|---|---|---|
| 工程骨架与健康检查 | — | `GET /health`、`GET /api/v1/health/db`、`scripts/start.ps1 health` |
| 家庭、成员与字段授权 | 成员档案、授权管理 | `GET /api/v1/households`、`POST …/authorizations`；越权读取返回结构化拒绝 |
| 健康事件、投影与 outbox | 家庭总览、我的记录 | `POST …/events` 追加不可覆盖事件；`GET …/outbox` 看补偿队列（Compose 已内置 outbox worker） |
| 规则风险与确认 | 用药安全 | `POST …/rules/run` 重算，`GET …/members/{id}/risks` 看风险卡与确认入口 |
| 照护计划与漏服升级 | 健康计划、服药提醒 | `…/plans/confirm`（另有 defer/skip/missed）；care-plan worker（HCT-308）已随基础档启动，每 30 秒评估一次（`CARE_PLAN_POLL_SECONDS`） |
| 视觉质量门控（图片/短视频） | 视觉扫描 | `POST /api/v1/vision-quality/check`；`RETAKE` 时必须重拍，不会继续入库 |
| 人工复核 | 人工复核 | 复核任务接口 `…/review-tasks/{id}/confirm`（另有 correct/skip） |
| 本地知识检索（RAG 接口） | 知识文档 | `GET /api/v1/knowledge/documents`、`POST /api/v1/knowledge/retrieve` |
| 助手接口与多智能体编排 | 健康助手 | `GET /api/v1/assistant/agents`；未配置 Ollama 模型时回答为**结构化降级**，不冒充生成 |
| 健康资讯（默认 local） | 家庭总览 | `GET /api/v1/health-news` 返回 `status=local_only` 季节提醒，不出网 |

本地进程路径（路径 B）不自动启动两个 worker，需要时手动运行（PYTHONPATH 含 `src/api` 与 `src`）：

```powershell
uv run python -m app.outbox_worker --loop
uv run python -m app.care_plan_worker --loop
```

### 有条件开启（照着做即可点亮）

| 功能 | 需要准备 | 关键 `.env` 项 | 如何验证 | 未配置时行为 |
|---|---|---|---|---|
| 正式账号密码登录 | 通过受控 API/脚本预置账号（演示可运行 `seed_formal_demo_health.py`） | `CURSOR_SIGNING_KEY`（生产必须换） | 两个入口都只显示正式账号、密码和用途；请求使用 Bearer 且无 `X-Actor-Id` | 未开户时登录失败，不回退开发身份 |
| 人脸凭证实验能力（不作为 Web 登录入口） | 本地 YuNet+SFace ONNX 模型：`uv run python scripts/ensure_face_models.py` | `FACE_MODEL_DIR`、`FACE_MODEL_AUTO_DOWNLOAD`、`FACE_MATCH_THRESHOLD_SFACE`、`BIOMETRIC_ENCRYPTION_KEY` | capabilities 可出现 `face-recognition-local`；历史凭证管理和后端契约保留 | 欢迎页仍只显示账号密码 |
| 视觉识别闭环（OCR/条码/YOLO） | 独立 PaddleOCR Python + `scripts/vision_worker.py`（权重不进 Git） | `OCR_VERSION`（≠`unavailable` 时 capabilities 亮 `vision-inference`）、`VISION_ADAPTER_SIGNING_KEY`（= worker 的 `HCT_ADAPTER_SIGNING_KEY`）、`MASTER_DATA_APPROVED_VERSIONS` | 上传合成药盒后任务进入四态并转人工复核；worker 日志 `ocr:true` | 任务保持排队/降级，质量门控与人工复核仍可用 |
| 教学演示主数据（HCT-201 教学路径） | `uv run python scripts/setup_vision_demo.py` 生成合成快照 | `MASTER_DATA_APPROVED_VERSIONS=demo-cn-en-v1` | capabilities 出现 `master-data-teaching-demo` | fail-closed 不加载；`hct201-formal-drug-set` 恒为 unavailable |
| 本地助手真实生成（Ollama） | 本机 Ollama 及模型，或增强档容器（`$env:COMPOSE_PROFILE='enhanced'` 后 `up`，容器内仍需 `ollama pull`） | `OLLAMA_BASE_URL`、`OLLAMA_MODEL`；本地默认 `AGENT_OPEN_CHAT=true`（见 [助手开放演示模式](docs/助手开放演示模式.md)） | 助手页真实回答；开放模式下少被证据墙打断 | 结构化降级，档案/规则/知识链路不受影响 |
| 可选联网搜索（HCT-430） | 夹具：完全不出网；真实：HTTPS 白名单 | 夹具：`AGENT_WEB_SEARCH_PROVIDER=fixture`；真实：`duckduckgo_html` + `AGENT_WEB_SEARCH_URL` + `AGENT_WEB_SEARCH_ALLOWED_DOMAINS`（见[专文](docs/demo/联网搜索与知识库刷新启用指南.md)） | 夹具：`web_search_ready=true` 但 capabilities **无** `external-web`；真实：capabilities **有** `external-web`；每次提问还需勾选「补充联网参考」 | 默认关闭（`DEPLOYMENT_DISABLED`），结果只是「外部参考」 |
| 知识入库与受控爬虫 | 知识管理员身份（`demo-` 前缀即可演示） | `KNOWLEDGE_ADMIN_ACTORS`（正式部署） | 「知识文档」页「一键教学闭环：抓取 → 批准 → 晋升」；`GET /api/v1/knowledge/crawl/status` | 爬虫默认离线夹具、**永不 auto_ingest**；非管理员看到明确提示 |
| 演示造数与课堂剧本（HCT-499） | 正式演示账号 `demo-parent` | 运行 `uv run python scripts/seed_formal_demo_health.py` 预置账号和虚构数据 | 「家庭与研发 → 演示造数」一键补种（幂等）；`POST /api/v1/demo/formal-health-seed`、`GET /api/v1/demo/classroom-scenarios` | 非演示身份被 403 `DEMO_SEED_FORBIDDEN` 拒绝（守卫生效，不是故障） |
| 天气行动卡（HCT-305） | 白名单天气源 | `WEATHER_ADAPTER=enabled`、`WEATHER_API_URL`、`WEATHER_DEFAULT_CITY_CODE`、`WEATHER_LOCATION_WHITELIST`、`EGRESS_WEATHER_WHITELIST` | `GET /api/v1/weather/action-cards` | 默认 `disabled`，返回结构化空响应；只允许发送 6 位行政区划代码 |
| 健康资讯真实抓取（HCT-445） | 白名单资讯域名 | `HEALTH_NEWS_ADAPTER=enabled`、`HEALTH_NEWS_ALLOWED_DOMAINS` | `GET /api/v1/health-news` 返回白名单来源条目 | 默认 `local` 仅季节提醒，不出网 |

联网搜索与知识爬虫的分步教程（含排障表）见[联网搜索与知识库刷新启用指南](docs/demo/联网搜索与知识库刷新启用指南.md)；视觉识别闭环见[视觉演示说明](docs/demo/vision-samples/README.md)；Ollama 模型准备见[本地大模型闭环](docs/demo/local-llm-v5.md)。改任何 `.env` 项后都必须重启 API（Compose：`down` 再 `up`）才生效。

### 仍需额外准备或尚未交付（诚实边界）

- `hct201-formal-drug-set`：正式药品固定集 **UNRELEASED**，`scripts/hct201_fixed_set_gate.py` 保持 fail-closed；教学路径只能指向合成的 `demo-cn-en-v1`。
- 人脸默认阈值来自公开样例，正式演示前须在本机用 `scripts/calibrate_face_thresholds.py` 按家庭摄像头标定（云端无法代采真人脸）。
- 微调 GGUF（v5）未完成正式评估，输出仅教学演示；HCT-408 三档部署/备份恢复演练仍在进行中。
- 随身版 Android APP 在 [`APP/`](APP/README.md) 独立维护，联机同一 FastAPI 后端；构建与验收以其自述文档为准。

**安全提醒：** 不提交 `.env`、真实健康数据、账号密码、密钥、模型权重与运行日志；`change-me` / `dev-only-*` 占位密钥仅限本机开发；`ALLOW_DEV_ACTOR_HEADER` 必须保持关闭并替换全部签名/加密密钥。当前本地短期会话仍不等于互联网生产认证。

## 核心价值

家庭中的药品、检查报告、过敏史、指标、计划和照护关系经常分散且不断变化。家健镜将每次变化保存为不可覆盖的 `health_event`，再重建当前状态、重算规则并生成照护任务，因此能回答：

- 最近发生了什么变化；
- 哪些事实、规则和文档导致新风险；
- 当前结果是否经过本人或照护者确认；
- 下一步需要谁处理、何时升级。

这里的「孪生」是家庭健康运营型数字孪生，不模拟人体生理，也不宣称预测疾病。

## 六个 P0 功能域

| 功能域 | P0 交付 | 明确边界 |
|---|---|---|
| 家庭健康事件中心 | 成员、疾病、过敏、指标、药物、文档、授权与事件时间线 | 不接医院 HIS 和全量可穿戴设备 |
| 多证据视觉录入 | 图片/短视频质量检查、YOLO 辅助定位、OCR、条码、包装特征、本地主数据和人工复核/修正 | 不承诺识别任意药品；未知/冲突不得自动入库 |
| 家庭健康关系图谱 | 成员—疾病—过敏—药品—成分—计划—照护者关系投影 | P0 不引入大规模医学本体或自动医学推理 |
| 风险与环境规则 | 过期、临期、低库存、重复成分、过敏、有限相互作用、天气行动卡和四级提醒 | 不是临床决策支持；普通告警有预算，严重告警不被压制 |
| 受约束计划优化 | 服药确认、延期、跳过、照护升级及安全时间窗内提醒建议 | AI 不得新增、停用、替换药物或改变剂量 |
| 本地证据助手与大屏 | SQL/图谱/RAG 工具调用、风险解释、事件摘要、业务与模型指标、字段级可见范围 | 无证据不作肯定性医学回答；无购药/问诊/广告入口 |

## 双闭环主链

```mermaid
flowchart TD
    A["药品图片 / 报告 / 短视频 / 手工录入"] --> B["OpenCV 质量门控、校正、抽帧去重"]
    B --> C["全图 OCR 主链路"]
    C --> D["YOLO 辅助包装/条码区域定位"]
    D --> E["条码解码 + 规则/主数据/LLM 字段抽取"]
    E --> F{"MATCHED / CONFLICT / UNKNOWN / REVIEW"}
    F --> G["人工确认或修正"]
    G --> H["追加不可覆盖的 health_event"]
    H --> I["重建成员状态与关系投影"]
    I --> J["确定性规则计算风险和任务"]
    J --> K["RAG 检索版本化证据"]
    K --> L["本地 LLM 解释并输出引用"]
    L --> M["本人或授权照护者确认，审计留痕"]
    G --> N["困难样本池"]
    N --> O["审核、追加训练、固定集评测、发布或回滚 V2"]
```

视觉系统允许拒识。只有人工确认的药品可参与风险计算；LLM 不计算风险等级，只解释规则结果。

## 计划架构

```mermaid
flowchart TB
    UI["Vue 3 + TypeScript + Vite"] --> GW["Nginx / HTTPS"]
    GW --> API["FastAPI 统一业务 API"]
    API --> AUTH["身份、成员级授权与审计"]
    API --> EVENT["事件、状态、计划与任务服务"]
    API --> ORCH["AI 编排与输出校验"]
    AUTH --> DB[("MySQL 事实主库 / 本地 SQLite")]
    EVENT --> DB
    ORCH --> CV["OpenCV / OCR / YOLO 辅助 / 条码"]
    ORCH --> RULE["关系投影与版本化规则"]
    ORCH --> RAG["本地知识检索 + 版本化文档"]
    ORCH --> LLM["Ollama 本地量化模型"]
    DB --> FILES["加密本地文件与模型存储"]
```

前端不得直连数据库、向量库或 Ollama。MySQL（Compose）或 SQLite（本地进程）是业务事实源；图谱是可重建投影；规则给出确定结论；LLM 负责工具选择、引用和语言解释。家庭版网络出口默认拒绝；天气只可发送城市/区县代码。

## 技术基线

- Web：Vue 3、TypeScript、Vite；页面主题在应用内切换，不依赖 Element Plus
- API：Python 3.11、FastAPI、Pydantic、SQLAlchemy 2、Alembic
- 数据：Compose 用 MySQL 8.4；本地进程默认可 SQLite
- 视觉：OpenCV 质量门控；PaddleOCR / 条码 / YOLO 辅助定位由本机 worker 按需加载
- 大模型：Ollama 本地推理；微调与评测在研发机进行，权重不入库
- 测试：pytest、httpx、Playwright、Vitest
- 部署：Docker Compose profile `basic` / `enhanced` / `dev`

## 仓库结构

```text
docs/vibe-coding/   需求、架构、数据、AI、测试、计划和交付基线
docs/stories/       当前可执行 Story、验收条件和复核要求
docs/decisions/     架构决策记录
docs/demo/          受控演示知识、视觉样例与本地模型接线
src/web/            产品 Vue 前端
src/web/react/      React 风格来源 / 教学页，不作为默认运行时
src/api/            FastAPI 业务 API
src/ai/             视觉与本地模型适配器
tests/              单元、契约、集成、E2E 与安全测试
migrations/         MySQL/SQLite 兼容的 Alembic 迁移
scripts/            启动、迁移、worker、检查脚本
docker/             API/Web 镜像和 Nginx 配置
```

## 开始协作

0. 先阅读[开发前必读与 Vibe Coding 工作流](docs/vibe-coding/开发前必读与Vibe%20Coding工作流.md)；agent 还必须遵守 [`AGENTS.md`](AGENTS.md)。
1. 再阅读[文档导航](docs/vibe-coding/00-文档导航.md)和[需求规格](docs/vibe-coding/01-需求规格说明书.md)。
2. 从[需求追踪矩阵](docs/vibe-coding/12-需求追踪矩阵.md)领取尚未完成的需求。
3. 按[贡献指南](CONTRIBUTING.md)从 GitHub `master` 拉任务分支，用 PR 合并。
4. 只有在代码、测试和复现证据合并后，才把状态改为「已验证」。
