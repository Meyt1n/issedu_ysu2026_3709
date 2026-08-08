# HomeCare Twin 本地部署与 Demo 操作指南

> 家庭版默认不把健康数据发送到互联网。Demo 必须优先使用本地基础档/增强档；任何云端扩展都不属于默认演示路径。

## 1. 当前可执行状态

一期工程骨架已经可以运行健康检查、数据库迁移、家庭/成员/授权和手工确认事件链。HCT-003 已增加 MySQL、OpenCV 质量探针和 Ollama 结构化资源探针，但视觉权重、规则集、RAG、完整 Ollama 业务助手、天气和完整十页仍未实现，不能把资源探针当作完整产品。

### 1.1 干净环境标准复现路径

以下路径是 HCT-101 的唯一基础档复现入口。`up` 使用 Docker Compose 构建 API/Web，等待 MySQL、API 和 Web 的健康检查，并在 API 容器启动时执行 Alembic 迁移；`down` 默认不删除 `mysql_data` 卷。

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

`health` 会同时检查 Compose 中 API、Web、MySQL 的容器健康状态，并访问 API 与 Web 的 `/health`。默认浏览器入口为 `http://localhost:8080`，API 健康检查为 `http://localhost:8000/health`，OpenAPI 为 `http://localhost:8000/docs`。端口被占用时，在 `.env` 中修改 `API_PORT`、`WEB_PORT` 或 `MYSQL_PORT`，再重新执行 `up`。

### 1.2 本地进程开发路径

需要调试 Vue/FastAPI 时可以不启动 Compose 的 API/Web，但仍必须先安装依赖并执行迁移：

```powershell
scripts/start.ps1 setup
scripts/start.ps1 migrate
scripts/start.ps1 api
```

另开终端执行 `scripts/start.ps1 web`。Linux/macOS 将脚本名替换为 `scripts/start.sh`。该路径的 `/api/v1/health/db` 使用本地 `DATABASE_URL` 检查数据库，不能代替 Compose 三服务 `health`。

带卷删除数据库前必须先完成备份演练；标准 `down` 不会删除卷。确需清空教学数据库时，必须由负责人单独执行 `docker compose down --volumes` 并记录影响。

## 2. 三档运行目标

| 档位 | 服务 | 适用环境 |
|---|---|---|
| 基础档 | Vue、FastAPI、MySQL、规则、轻量 OCR | 低配置电脑；断网仍可管理档案、任务和历史证据；网络出口默认拒绝 |
| 增强档 | 基础档 + FAISS/Qdrant + Ollama 量化模型 | 建议 16 GB 以上内存；资源探针已验证，本地证据助手仍待实现 |
| 研发档 | 增强档 + 数据标注、训练、评测和模型登记 | GPU 工作站或短时云 GPU；不得在家庭端自动训练 |

MySQL、Ollama、向量检索和文件服务默认仅监听本机/容器网络，不暴露公网。

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

## 5. 后续必须补齐

- 正式 Ollama 业务工具、输出 Schema、模型登记、GPU/CPU 和模型权重哈希；
- 迁移回滚、备份恢复和删除传播的演练记录；
- 基础档和增强档的完整功能启动、停止与健康检查证据；
- Web、OpenAPI、业务大屏和模型大屏的真实地址；
- 全链路从全新克隆开始的复现记录、耗时和最低硬件，见[HCT-101 干净环境复现记录](reviews/HCT-101-工程骨架干净环境复现记录.md)；HCT-003 仅覆盖资源探针；
- 常见故障：数据库未就绪、模型缺失、OCR 超时、向量索引不匹配、磁盘不足。

## 6. 连续 Demo 剧本

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
