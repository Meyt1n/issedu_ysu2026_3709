# HCT-448：Web 前端成熟产品排版重构（去侧栏滚动条与卡片堆叠）

- Issue：[#62](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/62)（HCT-306 家庭大屏/总览呈现主任务；相关 [#72](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/72) 可访问性不回退、[#386](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/386) 门户分流不回退）
- 需求：FR-09（家庭总览/大屏页面）、FR-01（本地隐私与授权状态常驻可见）、NFR-07（可访问性不得回退）、NFR-04（LLM/视觉降级时仍可用）
- 状态：进行中
- 负责人：Cloud Agent（Cursor）
- 复核人：维护者（merge 即代表人工复核完成）
- 风险：R1（纯呈现层重构，不改 API、授权、健康事件、规则、模型和医疗文案边界）
- 允许修改：`src/web/src/**`（App 外壳、style.css、Overview/MemberHome/Welcome/Members 等视图与相关组件样式）、`tests/browser/**`（仅同步选择器与进入路径，保留行为断言）、本 Story、`docs/vibe-coding/12-需求追踪矩阵.md`

> 编号说明：任务原定 Story 编号 HCT-447，但 `master` 于 2026-08-25 已被
> [PR #442](https://github.com/Meyt1n/issedu_ysu2026_3709/pull/442) 用于「侧栏助手导航唯一高亮」。
> 按 Story 编号唯一原则顺延为 HCT-448，并在此记录冲突，不复用既有编号。

## 用户价值

让正式 Vue 前端（`src/web`）看起来和用起来都像成熟交付产品：左侧导航一屏放下、不再出现明显滚动条；家庭总览从「层层玻璃卡片 + 左重右空」变成密度均衡的运营工作台；日常照护页面不再出现开发/演示脚手架文案；正式登录成为欢迎页的第一入口。

## 范围

1. **侧栏无滚动条**：压缩品牌区、分组标题与导航项的高度与字号，使管理员五组导航 + 品牌 + 底部隐私说明在 100dvh（1280×800 / 1440×900）内完整放下；短视口仍保留 `overflow-y: auto` 以保证键盘/缩放可达，但用 `scrollbar-width: none` 与 `::-webkit-scrollbar { display: none }` 隐藏滚动轨道。
2. **家庭总览重排**（最高优先级）：
   - 顶部改为一条紧凑头带：问候 + 成员切换 + 快捷操作 + 四项关键指标（成员/已确认事件/风险信号/待复核）内联展示，不再是四张独立卡片；
   - 主工作区改为等宽三列：待确认事项 / 今日用药 / 近期变化，同高、填满；
   - 次级带：天气与健康新闻等宽两列；家庭成员状态改为表格式行 + 最近识别的药品并列两列；
   - 本地运行/授权状态改为页面底部细状态条，不再是孤立右栏；
   - 删除印章、笔刷下划线、3D 倾斜快捷大卡与 `grid-main-side`（1.55fr/1fr 左重右空）结构。
3. **设计系统扁平化**：`.card`/`.row-card` 从玻璃拟态改为「实底 + 1px 边框 + 小圆角」的克制样式；内容区最大宽度从 1120px 放宽到 1340px；保留全部主题令牌（--paper/--pine/--clay 等），六套主题继续可切换。
4. **成员前台**：MemberHome 保持大触控目标，但复用扁平化卡样式并修正「教学观察值」等文案；成员状态映射、门户守卫、任务轮询逻辑不变。
5. **欢迎页层级**：正式账号登录成为默认与第一选项；「开发演示」入口保留（受 `VITE_SHOW_DEV_LOGIN` 门控）但退居第二位，不再是默认激活的视觉中心。
6. **去开发脚手架文案**：MembersView 占位符「空腹 / 早餐前（演示）」「教学观察值，非诊断」等改为产品化文案；大屏「教学演示系统」表述改为「家庭健康记录」，但保留必须的产品/法务文案：「健康数据默认只保存在本地」、不提供诊断/处方/用药决策边界、紧急联系医生提示、「不用于诊断或治疗」使用边界。

## 非目标

- 不改后端 API、鉴权、授权、健康事件、规则、模型或知识行为；
- 不新增医疗功能，不出现诊断/处方/买药/问诊/广告文案；
- 不用 React 替换 Vue，不重写 `src/web/react` 与 `APP/`；
- 不移除 Demo Lab（管理员研发工具）与「开发演示」登录（保持 SHOW_DEV_LOGIN 门控）；
- 不宣称 P0 关闭；HCT-306/HCT-409 的剩余人工验收不由本 Story 关闭。

## Given / When / Then

- Given 管理员在 1280×800 或 1440×900 进入后台；When 侧栏渲染五组导航；Then 品牌 + 全部导航 + 底部隐私说明在一屏内完整可见，侧栏不出现可见滚动条（`scrollHeight <= clientHeight` 或滚动条被视觉隐藏）。
- Given 管理员打开家庭总览；When 数据加载完成；Then 首屏出现问候头带（含四项指标）与等宽三列工作区（待确认事项/今日用药/近期变化），无 1.55fr/1fr 左重右空结构，识别候选仍标注「识别候选，不是健康事实」。
- Given 任一依赖（天气/风险/计划）不可用或为空；When 对应分区渲染；Then 显示一句话空态/降级文案，不伪造数据，也不留大面积空白列。
- Given 用户切换六套主题任意一套；When 页面重绘；Then 扁平化卡片、侧栏、头带均按主题令牌着色，无残留旧玻璃硬编码色。
- Given 键盘/读屏用户；When 遍历页面；Then 保持 lang=zh-CN、唯一 main/h1、可见焦点环、role=alert 错误播报，375px 视口无横向溢出（hct409 全部用例通过）。
- Given 家庭成员账号登录；When 进入成员前台；Then 门户分流（HCT-439）与成员风险/照片状态文案不变，只有视觉样式扁平化，且不出现教学/演示脚手架文案。
- Given 访问欢迎页；When 页面加载；Then 默认展示正式账号登录；「开发演示」仅在 SHOW_DEV_LOGIN 构建可见且需要主动切换。

## 测试与证据

- `npm run check:web`：TypeScript 类型检查；
- `npm run test:web`：Vitest 单元测试；
- `npm run build:web`：Vite 生产构建；
- `npm run test:e2e:web -- tests/browser/hct409-accessibility.spec.ts tests/browser/hct405-visible-workflows.spec.ts tests/browser/hct439-member-portal.spec.ts tests/browser/hct418-web-e2e.spec.ts tests/browser/hct416-vision-review.spec.ts`：可访问性、管理员工作流、成员门户、E2E 视口约束回归（进入路径按「正式登录默认、开发演示需切换」同步，行为断言保留）；
- `git diff --check`：空白检查。

## 已知限制

- 真实后端联调（scripts/start.sh web + API）在本增量环境不可用时，以 Playwright 合成 API 证据为准，真实环境人工走查仍需维护者在本地复核；
- hct409 的人工读屏（NVDA/VoiceOver）R3 复核不在本 Story 内，仍按 HCT-409 计划执行。

## 回滚

仅涉及 `src/web` 前端模板/样式与浏览器测试选择器，无迁移、无 API 变更、无依赖变更。revert 本 Story 对应提交即可完整恢复原布局；不影响后端事实、授权、事件、规则与模型。
