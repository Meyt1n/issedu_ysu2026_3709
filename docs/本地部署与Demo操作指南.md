# HomeCare Twin 本地部署与 Demo 操作指南

> 家庭版默认不把健康数据发送到互联网。Demo 必须优先使用本地基础档/增强档；任何云端扩展都不属于默认演示路径。

## 1. 当前可执行状态

一期工程骨架可以运行健康检查、数据库迁移、家庭/成员/授权、不可变事件、兼容幂等与补偿、可恢复 outbox worker 和投影重放。仓库内还有视觉质量门控、OCR-first 证据、人工复核、本地知识检索和受约束助手接口；**权重、PaddleOCR 环境和微调模型不进 Git**，未配置时助手与识别应降级而不是假装完成。

正式药品固定集、模型发布、三档备份恢复演练和 R3 验收仍未关闭。不能把资源探针当作完整产品，也不能把质量门控或本机实验模型当成完整产品。总入口见根目录 [README](../README.md)。

### 1.1 干净环境标准复现路径

以下路径是 HCT-101 的基础档复现入口（工程骨架）。视觉识别与本地助手闭环已合入 `master`，无需切换功能分支；按功能开启的总入口见根目录 README 的[「功能与 API 启动指南（按功能开启）」](../README.md#功能与-api-启动指南按功能开启)与「复刻本机视觉与助手闭环」。

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

`health` 会同时检查 Compose 中 API、outbox worker、care-plan worker、Web、MySQL 的容器健康状态，并访问 API 与 Web 的 `/health`。默认浏览器入口为成员前台 `http://localhost:8080` 与管理后台 `http://localhost:8081`（HCT-453，见 §1.4），API 健康检查为 `http://localhost:8000/health`，OpenAPI 为 `http://localhost:8000/docs`。端口被占用时，在 `.env` 中修改 `API_PORT`、`WEB_PORT`、`ADMIN_WEB_PORT` 或 `MYSQL_PORT`，再重新执行 `up`。

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

完整的录入/刷脸登录逐步操作、常见错误速查与排障请看专文：[人脸凭证录入与登录操作手册](demo/人脸凭证录入与登录操作手册.md)。

**Windows 中文路径注意（2026-08-26 修复）**：此前仓库路径含中文（如 `C:\...\多模态医疗\...`）时，OpenCV 在 Windows 上无法读取 YuNet/SFace ONNX 文件，注册/登录报 HTTP 500 并把本机路径泄漏进提示。现已改为 Python 读取权重字节 + OpenCV 内存缓冲加载，中文路径可正常工作；残余加载失败只返回 503 `FACE_DETECTOR_UNAVAILABLE` 与中文指引。仍建议仓库使用纯英文路径（其它工具链如 Docker 卷挂载对中文路径的兼容性无法保证）；排查步骤见操作手册 §3。

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

另开终端执行 `scripts/start.ps1 web-member`（成员前台 5173）；需要管理后台时再开一个终端执行 `scripts/start.ps1 web-admin`（5174）。调试也可用原 `scripts/start.ps1 web`（单入口，按账号角色进门户）。Linux/macOS 将脚本名替换为 `scripts/start.sh`。本地进程路径不会自动启动 outbox worker；该路径的 `/api/v1/health/db` 使用本地 `DATABASE_URL` 检查数据库，不能代替 Compose 服务级 `health`。

带卷删除数据库前必须先完成备份演练；标准 `down` 不会删除卷。确需清空教学数据库时，必须由负责人单独执行 `docker compose down --volumes` 并记录影响。

### 1.4 前台 / 后台双入口怎么进（HCT-453）

一个家庭只有一个本地 API 和一套账号；前台和后台是**两个端口的登录入口**，共用同一份网页构建产物：

| 我是谁 | 应该打开 | 本地进程（路径 1.2） | Compose（路径 1.1） | 登录方式 |
|---|---|---|---|---|
| 家庭成员（长辈/家人） | 成员前台 | `http://127.0.0.1:5173`（`scripts/start web-member`） | `http://localhost:8080` | 人脸 / 家庭 PIN（账号密码收在「其他方式」里） |
| 家庭管理员（owner） | 管理后台 | `http://127.0.0.1:5174`（`scripts/start web-admin`） | `http://localhost:8081` | 账号密码（PIN/人脸主要供家人使用） |

- 两个登录页长得明显不同（HCT-455）：成员前台是「我的健康日常」个人登录页，只有人脸 / 家庭 PIN 两个主选项，主按钮是「进入我的前台」；管理后台是「家庭管理后台」管理员登录页，账号密码为主，主按钮是「进入管理后台」。页脚互跳链接会自动带上 `?portal=member|admin`，即使目标端口没有注入入口模式也按正确品牌显示。
- 走错入口不会泄露或损坏任何数据：登录成功后系统发现账号与入口不匹配，会立刻退出本次登录，并在页面上给出「去管理后台登录 / 回成员前台登录」按钮。
- 入口只是界面锁；谁能看什么、谁能改什么仍完全由服务端授权（HCT-439/HCT-102）决定。
- 端口自定义：本地进程 `HCT_WEB_PORT`（前台）/ `HCT_ADMIN_WEB_PORT`（后台）；Compose `.env` 的 `WEB_PORT` / `ADMIN_WEB_PORT`。非默认端口部署可在构建时设置 `VITE_MEMBER_PORTAL_URL` / `VITE_ADMIN_PORTAL_URL` 让跨端按钮指向正确公开地址。
- 调试用单入口 `scripts/start web`（5173，不设入口模式）保持旧行为：登录后按账号角色自动进前台或后台。

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

### 4.2 如何启用联网搜索（HCT-430，含离线教学夹具）

> **用户向分步教程（含排障表）：** [联网搜索与知识库刷新启用指南](demo/联网搜索与知识库刷新启用指南.md)

联网搜索默认关闭（`AGENT_WEB_SEARCH_ENABLED=false`），且必须**双重开启**：部署开关 + 每次请求在助手页勾选「补充联网参考」。未启用时助手页会显示不可用原因与本节指引；`/api/v1/assistant/agents` 返回 `web_search_ready` 与 `web_search_unavailable_reason`（`DEPLOYMENT_DISABLED` / `EGRESS_BLOCKED` / `OPT_IN_REQUIRED`）供排查。

### 4.2.1 助手开放演示模式（默认开启）

本地 Demo **默认** `AGENT_OPEN_CHAT=true`，便于直接看本机模型真实回复（跳过证据/引用硬墙与空库季节短接，并注入本机日期）。完整说明、自检步骤与生产强制关闭规则见专文：

→ [助手开放演示模式（HCT-451）](./助手开放演示模式.md)

若需恢复教学证据墙：`.env` 设 `AGENT_OPEN_CHAT=false` 后重启 API。

**路线 A：离线教学夹具（推荐课堂/无网演示，完全不出网）**

在 `.env` 中设置并重启 API：

```dotenv
AGENT_WEB_SEARCH_ENABLED=true
AGENT_WEB_SEARCH_PROVIDER=fixture
```

助手页勾选「补充联网参考」后，联网节点返回本机合成的教学夹具参考（域名固定为保留域 `fixture.invalid`，自带「教学夹具，非真实网页」标注），`agent_trace` 中该节点 `network_used=false`。夹具内容不构成医疗证据，只用于演示外部参考的展示样式。

**路线 B：真实联网（白名单出口）**

```dotenv
AGENT_WEB_SEARCH_ENABLED=true
AGENT_WEB_SEARCH_PROVIDER=duckduckgo_html
AGENT_WEB_SEARCH_URL=https://html.duckduckgo.com/html/
AGENT_WEB_SEARCH_ALLOWED_DOMAINS=html.duckduckgo.com
```

自建 SearXNG 可改用 `AGENT_WEB_SEARCH_PROVIDER=searxng` 并把 URL/白名单指向实例地址。硬边界不变：仅发送脱敏后的问题（自动移除 ID/手机号/邮箱/成员姓名），不发送任何健康记录；外部结果单独放在 `external_sources`，页面标注「外部参考（非本地审核证据）」，永不进入本地引用；搜索失败只降级联网节点，不影响本地档案/规则/知识链路。

验证命令（重启 API 后）：

```powershell
curl.exe http://localhost:8000/api/v1/assistant/agents -H "X-Actor-ID: demo-parent"
# 期望 web_search_ready=true 且 web_search_unavailable_reason=OPT_IN_REQUIRED
```

### 4.3 如何刷新知识库（HCT-401 受控爬虫闭环）

> **用户向分步教程（含排障表）：** [联网搜索与知识库刷新启用指南](demo/联网搜索与知识库刷新启用指南.md)

知识爬虫只抓 `docs/knowledge/crawl/allowlist.json` 白名单来源，默认仅本地夹具；结果进入 staging 草稿，**永不 auto_ingest**。Web 入口在「知识文档」页右侧「知识爬虫 / Staging」卡片，仅知识管理员可见可操作：演示身份用 `demo-parent`、`knowledge-steward` 或任意 `demo-` 前缀账号；正式部署把账号加入 `.env` 的 `KNOWLEDGE_ADMIN_ACTORS`（逗号分隔）后重启 API。非管理员会看到明确的「需要知识管理员身份」提示。

Web 一键教学闭环：点击「一键教学闭环：抓取 → 批准 → 晋升」按钮即可完成夹具抓取、批准与晋升，页面随后展示 dry-run 入库命令。等价 CLI：

```powershell
# 抓取白名单夹具到 staging（默认离线；远程源需 allowlist enabled + --live）
uv run python scripts/crawl_knowledge_sources.py
uv run python scripts/crawl_knowledge_sources.py --status

# 审核并批准 → 晋升到 approved/incoming
uv run python scripts/promote_knowledge_staging.py review --source-id fixture-med-storage --reviewer alice --approve
uv run python scripts/promote_knowledge_staging.py promote --actor-id knowledge-steward

# dry-run 预检查通过后再去掉 --dry-run 正式入库（独立 index-version）
uv run python scripts/ingest_local_knowledge.py `
  --manifest docs/knowledge/approved/incoming/正式知识清单.crawl.json `
  --source-root docs/knowledge/approved `
  --actor-id knowledge-steward `
  --index-version approved-crawl-v1 `
  --dry-run
```

API 侧 `/api/v1/knowledge/crawl/run` 强制离线夹具（服务端不出网）；远程刷新只能走 CLI `--live` 且要求 allowlist 中 `enabled: true` 并命中 `policy.allowed_hosts`。详见 [知识爬虫 README](knowledge/crawl/README.md)。

### 4.4 HCT-201 教学演示主数据（INTERNAL_TEACHING_DEMO）

药品主数据分两条完全独立的路径，演示与文档必须诚实区分：

- **教学演示路径（可开启）**：合成主数据 `demo-cn-en-v1`，批准范围为
  [HCT-201 教学演示批准范围 V1](data/HCT-201-教学演示批准范围-V1.md)（`INTERNAL_TEACHING_DEMO`，
  `formal_release_eligible: false`）。快照内容全部为合成教学数据，无真实药品来源。
- **正式药品集（仍 UNRELEASED）**：`scripts/hct201_fixed_set_gate.py` 保持 fail-closed；在来源授权、
  真实实体/会话分组、fixed/unknown/conflict 冻结、删除演练与 R3 复核证据齐备前，任何人不得把教学
  范围或隔离候选登记为正式发布集。

开启教学演示路径（默认关闭，fail-closed）：

```bash
# 1. 生成合成教学快照（写入 data/master-data/demo-cn-en-v1.json，该目录不入库）
uv run python scripts/setup_vision_demo.py

# 2. 在 .env 中批准该版本（Compose 会把变量透传给 api 容器，
#    并把 ./data/master-data 以只读方式挂载进容器）
# MASTER_DATA_APPROVED_VERSIONS=demo-cn-en-v1

# 3. 重启 API / 重新执行 up 后验证：
curl http://localhost:8000/api/v1/meta/capabilities
```

`/api/v1/meta/capabilities` 会诚实反映两条路径：教学快照已批准且校验通过时 `available` 包含
`master-data-teaching-demo`；`hct201-formal-drug-set` 始终在 `unavailable`，直到正式门禁以真实证据
通过。快照的加载校验（版本白名单、schema、SHA-256、批准/撤销状态）不会因教学范围放宽；识别候选
仍必须人工确认后才能入档。

### 4.5 演示造数与课堂剧本（一键补种，HCT-452）

「演示造数」页可一键补种正式演示家庭（爷爷奶奶家）的虚构病史、过敏、药品、指标、计划与提醒闭环事件，全部标注「演示」，不含真实健康数据。补种使用固定幂等键，重复点击或超时重试都不会产生重复数据。

**前置与步骤：**

1. 先把 API 和 Web 跑起来（§1.1 Compose 或 §1.2 本地进程均可）；本地进程路径要求 API 在 8000 端口、`scripts/start.ps1 web`（或 `.sh`）在 5173。
2. 用演示身份进入家庭空间：开发身份填 `demo-parent`（或其它 `demo-` / `test-` 前缀账号；开发身份头需要 `ALLOW_DEV_ACTOR_HEADER=true`）。要走正式账号会话，可先在欢迎页「正式账号登录 → 注册」为 `demo-parent` 设置本地密码；命令行 `uv run python scripts/seed_formal_demo_health.py` 不带 `--dev-header` 时会自动注册并使用默认教学密码 `DemoOnly-ChangeMe!`。非演示身份会被后端 403 `DEMO_SEED_FORBIDDEN` 拒绝，页面会引导改用演示身份——这是守卫生效，不是 API 故障。
3. 打开「家庭与研发 → 演示造数」，点击「补种 / 重置演示健康数据」。成功后页面展示 `events_touched` 报告并自动切到演示家庭；课堂剧本三条固定路径可直接跳转对应页面。等价命令行：`curl -X POST http://localhost:8000/api/v1/demo/formal-health-seed -H "X-Actor-ID: demo-parent"`。

**红条排障对照（错误分层）：**

| 页面提示 | 实际含义 | 处理 |
|---|---|---|
| 本地 API 服务不可用…请确认 API 已在 8000 端口运行 | 浏览器拿不到任何 API 响应，或代理（Vite dev / Nginx）连不上 API 进程 | 本地进程：确认 `scripts/start api` 终端仍在运行；Compose：`scripts/start.ps1 health` 检查 api 服务 healthy；远程隧道检查隧道连通 |
| 当前身份无权补种演示数据：请改用 demo-parent… | 后端 `DEMO_SEED_FORBIDDEN` 守卫拒绝非演示身份，API 正常 | 切换为 `demo-parent` 或其它 `demo-` / `test-` 前缀身份 |
| 课堂剧本加载失败：… | 只读剧本接口失败，与补种无关；红条显示在剧本卡片并带「重新加载剧本」按钮 | 按提示排查 API 连接后点「重新加载剧本」 |
| 需要先填写开发身份才能继续这次请求。 | 请求没有携带身份（401） | 回到欢迎页填写开发身份或登录正式账号 |

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
