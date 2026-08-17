# 家健镜随身版 HomeCare Twin Companion

> 家健镜 HomeCare Twin 的随身照护移动端（教学演示，不用于诊断或治疗）。
>
> 配套主仓库（网页端 + FastAPI 后端）：[issedu_ysu2026_3709](https://github.com/Meyt1n/issedu_ysu2026_3709)

家健镜随身版是移动端应用（H5 + Capacitor 安卓壳）：老人和照护者用手机完成**每天真正高频的照护动作**——确认服药任务、拍药盒录入、查看分级提醒和一键求助；管理、复核、大屏和模型实验室等重度操作仍由网页端承担。两端共用同一套术语与 API 契约；移动端拥有**独立的视觉体系**（暖奶油底 + 森林绿 + 蜜桃琥珀，渐变英雄卡、任务进度环、悬浮胶囊导航），按移动场景与适老审美设计，不复刻网页端样式。

> **产品硬承诺（与主仓库一致）：** 家庭健康数据默认不出网；药盒识别永远需要人工确认，冲突/未知不自动入库；照护者只能看到被精细授权的字段；风险等级由确定性规则决定，应用不做诊断、处方、停药、换药或剂量判断；无购药、问诊、广告导流。

## 与网页端的分工呼应

| | 网页端（主仓库） | 随身版（本仓库） |
|---|---|---|
| 定位 | 家庭工作台 | 随身照护端 |
| 典型场景 | 授权管理、人工复核、健康图谱、大屏、模型实验室 | 今日任务确认、拍药盒、看提醒、家人视图、紧急求助 |
| 使用者 | 家庭管理员、数据/模型管理员 | 老人、慢病成员、授权照护者 |
| 数据 | MySQL 事实主库（唯一事实源） | 同一 FastAPI API，仅授权范围内读写 |
| 术语 | 健康事件 / 风险四级 / 识别四态 / 授权范围 | 完全一致 |

## 功能页面

- **今日**：时段氛围英雄卡（任务进度环 + 滚动统计）+ 今日照护任务（确认 / 延期 / 跳过，跳过必填原因，完成反馈 Toast + 触觉震动，全部完成有彩带庆祝）+ 近 7 天完成趋势图 + 待关注风险 + 最近变化时间线；
- **拍药盒**：拍摄 → 质量门控 → 多证据候选（OCR/条码/主数据，四态 `MATCHED / CONFLICT / UNKNOWN / REVIEW`）→ 引导人工复核；
- **家人**：仅显示被授权的成员与字段，授权范围（可见字段、用途、到期时间）明示；未授权字段显示"未获授权"而非空数据；
- **提醒**：风险四级筛选（严重/较高/一般/提示），风险卡展开"为什么出现这条提醒 + 证据事件 + 非医疗处置建议"；
- **求助**：超大按钮拨打急救电话/联系家人、语音播报当前重要提醒（长辈模式下进入底部主导航）；
- **我的**：长辈模式开关、无障碍设置、紧急联系人、数据源切换、隐私与边界声明。

## 无障碍模式（核心特性）

- **长辈模式一键开启**：特大字号 + 语音播报 + 简化底部导航（今日/拍药盒/求助/我的）+ 更大触控目标（≥60px）；
- **外观三档**：浅色 / 深色（森林夜配色）/ 跟随系统，系统切换深浅色时实时生效；
- **字号三档**：标准 / 大 / 特大，全局 rem 缩放；
- **高对比度**：纯白实底 + 黑描边，自动去除玻璃、渐变、阴影与背景装饰，优先级高于深色模式；
- **语音播报**：Web Speech API（zh-CN）朗读今日安排、风险提醒与操作结果，支持手动"播报"按钮；
- **减少动效**：应用内开关 + 自动尊重系统 `prefers-reduced-motion`，停用包括背景漂移、扫描线、彩带、数字滚动在内的全部动画；
- **不只靠颜色**：所有等级/状态均为"文字 + 图标 + 颜色"三重表达（呼应主仓库 NFR-07）；
- 全部设置保存在本机 `localStorage`，不上传。

详细设计见 [docs/无障碍模式设计说明.md](docs/无障碍模式设计说明.md)。

## 技术栈

- Vue 3.5 + TypeScript 5.7 + Vite 6（与主仓库网页端同栈同版本）；
- vue-router 4（hash 路由，任意静态托管可用）；
- 无 UI 组件库：手写设计系统（玻璃拟态 + AI 生成水彩氛围底图 + 立体光影 + 浅/深/高对比三套材质变量联动；全部由 CSS 自定义属性驱动）；
- vitest + happy-dom 单元测试；
- PWA manifest + 离线 Service Worker（缓存应用外壳与静态资产；`/api`、`/health` 绝不缓存，健康数据不落缓存）；
- Capacitor 8 安卓壳：同一套 Web 代码打包为原生 Android 应用（见下文"安卓应用"）。

## 快速开始

```powershell
npm install
npm run dev        # 手机与电脑同一局域网时，可用命令行输出的局域网地址在手机上访问
```

检查与构建：

```powershell
npm run check      # vue-tsc 类型检查
npm run test       # vitest 单元测试
npm run build      # 产物输出到 dist/
```

## 数据来源与诚实状态说明

应用有两种数据模式（在"我的 → 数据来源"切换）：

| 模式 | 状态 | 说明 |
|---|---|---|
| 演示模式（默认） | 完整可体验 | 内置**虚构**家庭数据（人物、药品、风险均为编造，明确标注"演示"），不连接任何服务器，用于教学演示与交互验收 |
| 家庭服务器（联机） | 已与本地后端联调（2026-08-13） | 调用主仓库 FastAPI 既有接口；事件语义已按后端 `app/projection.py` 校准（见下） |

### 已联调验证的链路（2026-08-13，本地 SQLite 后端）

- 家庭 / 成员列表（含照护者视角的 API 层过滤：`X-Access-Purpose` 必须与授权 purpose 匹配）；
- 成员时间线（仅已确认事件，升序）与用药清单（由 `medication_added` 事件推导）；
- 确定性规则风险：`allergy_conflict`（SEVERE）与 `interaction`（INFO）经移动端链路可见，含证据事件详情；
- 今日任务：由 `plan_created` / `plan_updated` 计划事实 + 最后一条 `plan_confirmed` / `plan_deferred` / `plan_skipped` 动作事件推导；确认/延期/跳过写回事件中心（服务端按计划幂等）；
- 图片质量门控与视觉任务创建（识别候选确认仍在网页端复核中心完成，这是产品设计）。

### 联调步骤

```powershell
# 1. 在主仓库启动后端（独立 SQLite + 放开本页面所需 CORS）
#    默认用 18800 端口避开常见冲突；被占用时换任意空闲端口即可
$env:DATABASE_URL = "sqlite+pysqlite:///./homecare-mobile-demo.sqlite3"
$env:CORS_ORIGINS = "http://localhost:5173,http://localhost:5175,https://localhost,http://localhost,capacitor://localhost"
$env:PYTHONPATH = "<主仓库>\src\api;<主仓库>\src"
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir src/api --host 0.0.0.0 --port 18800

# 2. 在本仓库写入虚构联调数据（幂等，可重复执行）
npm run seed:live -- --base http://127.0.0.1:18800

# 3. 启动移动端（dev 代理默认指向 18800；连其它实例用 HOMECARE_API 覆盖）
npm run dev
```

应用内切到"我的 → 数据来源 → 家庭服务器"，身份填 `dev-wang`（owner）或 `dev-uncle`（仅被授权读王秀兰事件的照护者），目的代码保持 `family-care`。网页端（主仓库 `npm run dev:web`）连同一后端即可两端互通。

### 联机模式的已知限制（如实记录，不冒充完成）

- 药盒识别链路只到"创建视觉任务"，候选确认仍需回网页端人工复核中心；
- 风险"我已知晓"回写暂无对应服务端接口，界面会如实提示而不是伪装成功；
- 照护者视角的可见范围按"服务端已过滤"标注（授权明细仅 owner 可读，到期时间不显示）；
- "近 7 天完成情况"由计划事实与 `plan_confirmed` 事件推导，为近似统计；
- 登录 / PIN 二次确认沿用主仓库开发期的 `X-Actor-Id` 头约定，正式鉴权跟随主仓库 HCT-107 交付；
- 联调发现的主仓库缺口：投影丢弃药品 `expiry_date/stock/ingredient` 导致过期/低库存/重复成分规则无法触发——
  已提交修复（[Issue #140](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/140)、
  [PR #141](https://github.com/Meyt1n/issedu_ysu2026_3709/pull/141)，含"事件→投影→规则"回归测试，待维护者复核合并）。

## 安卓应用（Capacitor）

同一套代码通过 Capacitor 打包为原生 Android 应用，WebView 内置打包产物，联机数据走"我的 → 数据来源"里配置的家庭服务器地址（`AndroidManifest` 已允许家庭局域网明文 http）。

一键构建（推荐）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-apk.ps1
# 产物：android\app\build\outputs\apk\debug\app-debug.apk
```

手动步骤（等价）：

```powershell
npm run android:sync                 # 构建 Web 产物并同步到 android/ 工程
cd android
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"   # 或任何 JDK 21+
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
.\gradlew.bat assembleDebug
```

说明：

- 首次构建需要 Android SDK（Android Studio 自带）；`android/local.properties` 由本机自动生成，不入库；
- 仓库路径含中文目录时依赖 `android.overridePathCheck=true`（已配置），个别环境仍失败时可把仓库放到纯 ASCII 路径构建；
- 把 `app-debug.apk` 传到手机安装（需允许安装未知来源应用），或连接手机后 `npx cap run android`；
- 手机与家庭服务器需在同一局域网，服务器地址填电脑的局域网 IP，例如 `http://192.168.1.10:8000`。

## 目录结构

```text
android/             Capacitor 生成的原生安卓工程（构建产物与 local.properties 不入库）
public/              PWA manifest、图标、AI 生成氛围底图（bg/）与离线 Service Worker（sw.js）
scripts/             联调造数脚本（虚构数据）与一键 APK 构建脚本
src/
  api/               与主仓库对齐的 API 契约与客户端（X-Actor-Id 等请求头一致）
  components/        TabBar、任务卡、等级标签、开关等基础组件
  composables/       语音播报（Web Speech API）
  data/              DataProvider 接口 + 演示数据 + 联机适配器 + 文案映射
  router/            页面路由
  stores/            无障碍设置、会话设置（localStorage 持久化）
  utils/             时间格式化等
  views/             9 个页面
docs/                无障碍模式设计说明
capacitor.config.ts  安卓壳配置（appId、webDir）
```

## 边界与隐私

- 教学演示项目，不得用于诊断或治疗；紧急情况请联系医生或当地急救服务；
- 仓库中不包含任何真实健康数据、真实人物信息、密钥或模型权重；演示数据全部虚构；
- 应用不采集、不上传健康数据；联机模式仅连接家庭可信域内地址；
- 无购药、问诊、广告或佣金导流入口。

## 协作约定

本仓库遵循主仓库的开发治理基线（诚实状态、无真实数据、PR 流程），入口见 [AGENTS.md](AGENTS.md)。
