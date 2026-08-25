# HCT-450：Web 前端截图驱动排版修复与助手全屏对话

- Issue：待维护者创建后回填（本任务 agent 无 issues 写权限）；相关既有任务：
  Related to [#62](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/62)（家庭总览 dashboard）、
  Related to [#72](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/72)（前端可访问性）、
  Related to [#386](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/386)（门户分流）、
  Related to [#252](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/252)（助手会话体验）、
  Related to [#210](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/210)（助手语音）、
  Related to [#310](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/310)（多智能体协作）。
- FR/NFR：FR-09（页面信息架构与家庭可用性）、FR-08（本地证据助手）、FR-03（视觉扫描与复核入口）、FR-01（授权与凭证管理入口）、NFR-07（可访问与可理解）、NFR-04（资源与性能边界）。
- 风险等级：R1（纯前端展示层；助手布局触碰会话 UI，但不改 API、鉴权、医疗边界与降级语义）。
- 负责人：Cloud Agent（Cursor）；复核人：维护者（merge 即代表人工复核完成）。
- 背景：HCT-448 的整页“成熟产品重构”（PR #450）已被用户否决并由 PR #452 回退。本 Story 按用户提供的 11 张截图做**定点**修复，保留现有暖纸/松绿视觉语言，不再做全局重构。

## 用户价值

家庭管理员在总览、扫描、用药安全、图谱、助手、授权、人脸凭证、大屏、知识和欢迎页上看到的排版缺陷（内容溢出、左右失衡、大段说明文字挤占操作区、助手页信息倾泻）被逐项修复；健康助手升级为主流 AI 对话布局（全幅画布 + 会话历史 + 醒目输入框 + 设置抽屉），长辈和照护者能更快完成提问与核对。

## 范围（按截图逐条）

1. 图一 家庭总览：「01 待确认事项」列表溢出卡片底边 → 卡片内列表自滚动、不再溢出；空/密卡片高度更均衡。
2. 图二 视觉扫描：左侧虚线上传框与右侧「拍摄参考」面板等宽（1fr/1fr），虚线框放大，功能不变。
3. 图三 用药安全：压缩标题区 → 信号数字条 → 「01 风险信号与依据」之间的纵向空隙。
4. 图四 健康图谱：节点由平面圆升级为带渐变高光、柔和投影、缓慢浮动的“3D 球”效果；respect `prefers-reduced-motion`；图例、隐私说明与语义不变。
5. 图五/图六 健康助手（最高优先级）：
   - 除全局侧栏外全幅铺开的对话画布（`.view-assistant` 解除 1120px 卡片约束）；
   - 内层左侧会话历史栏（sessionStorage 本地多会话，仍按标签页隔离、退出清空，不新增后端 API）；
   - 大消息区 + 底部醒目输入框；
   - 唤醒词/静音/语音偏好/长说明文案移入右上角设置抽屉；
   - 多智能体流程收纳为顶部紧凑状态条（按需展开详情），不再占半页；
   - 联网搜索为一个简洁开关「联网搜索」，启用帮助收进设置抽屉；
   - 保留：成员选择、清空会话、证据引用、拒答降级、无诊断/处方边界。
6. 图七 授权管理：压缩表单纵向长度（两列字段、并排 fieldset）、左侧卡片减少空白，两栏更均衡；模板与编辑/续期/撤回功能不变。
7. 图八 人脸凭证：重排两栏（长的注册卡为主列，绑定家庭/账号/PIN 小卡为副列，凭证清单全宽），删除冗余长文案；采集功能不变。
8. 图九 家庭大屏：指标块与面板加入渐变、玻璃质感、层次投影与克制的悬浮动效；脱敏规则与免责声明不变；respect reduced-motion。
9. 图十 知识文档：重排为均衡分栏，联网搜索运行状态收为一行紧凑指标，删减运维说教文案；登记/列表/快照/爬虫审批功能不变。
10. 图十一 欢迎页人脸框：删除黑色扫描窗上的「1 正对 / 2 左转 / 3 右转」三个气泡（姿势引导保留在顶部横幅文字与语音播报中）；虚线/椭圆引导视觉权重对齐。

## 非目标

- 不重做全局排版（HCT-448 方案已回退，不复活）；
- 不改 `src/web/react` 与 `APP/`；
- 不新增或修改任何后端 API、鉴权、会话缓存协议、医疗边界与降级语义；
- 不引入 Three.js 等新重依赖；
- 识别候选仍标注「识别候选 / 待复核」，不改变复核链路。

## Given / When / Then

- Given 管理员打开家庭总览且待确认事项超过卡片高度；When 查看「01 待确认事项」；Then 列表在卡片内部滚动，内容不越过卡片边框。
- Given 管理员打开视觉扫描；When 对比左侧虚线上传框与右侧拍摄参考；Then 两者等宽且左框高度不小于右侧面板主体。
- Given 管理员打开用药安全；When 观察标题到信号条到风险区块；Then 无一屏内明显空段，纵向节奏紧凑。
- Given 管理员打开健康图谱且有节点；When 观察节点；Then 节点呈现渐变球体与柔和浮动；开启系统减少动态后浮动停止。
- Given 管理员打开健康助手；When 页面加载；Then 对话画布占满主区，左侧出现会话列表，设置齿轮收纳语音偏好与联网搜索说明，多智能体流程为紧凑状态条；发送问题后回答仍带引用与人工确认提示。
- Given 管理员新建会话并切换回旧会话；When 查看消息；Then 两个会话互不串扰，且仅保存在当前标签页。
- Given 用户打开欢迎页人脸登录或后台人脸注册；When 查看黑色扫描窗；Then 不再出现「1 正对 / 2 左转 / 3 右转」气泡，语音与顶部提示仍逐步引导，采集可完成。

## 允许修改范围

- `src/web/src/views/{OverviewView,ScanView,RisksView,GraphView,AssistantView,AuthView,FaceCredentialView,BigScreenView,KnowledgeView,WelcomeView}.vue`
- `src/web/src/components/FaceVideoCapture.vue`、`src/web/src/vision/VisionQualityPanel.vue`
- `src/web/src/assistant/chatSession.ts`（新增标签页本地多会话辅助函数，向后兼容）及其测试
- `src/web/src/style.css`、`src/web/src/App.vue`（仅 view-stage/assistant 布局约束）
- `tests/browser/*.spec.ts`（选择器/文案同步）
- 本 Story 与 `docs/vibe-coding/12-需求追踪矩阵.md`

## 测试与验收

- `npm run check:web`、`npm run test:web`、`npm run build:web`
- Playwright：`hct405-visible-workflows`、`hct409-accessibility`、`hct418-web-e2e`、`hct439-member-portal`（合成 API）
- 浏览器逐图截图核对（合成数据）
- `git diff --check`

## 回滚

纯前端展示层改动，单 PR 回退（`git revert`）即可恢复；不涉及依赖、迁移、配置或网络出口变化。

## 已知限制

- 助手多会话为标签页本地能力（sessionStorage），关闭标签页即清空；不提供跨设备会话同步（本地优先边界）。
- 3D 效果为 CSS/SVG 实现的轻量深度感，不是真实 3D 渲染。

## 验证记录（2026-08-25，本分支 `cursor/hct450-screenshot-ui-fixes-6901`）

- `npm run check:web`：通过（tsc 无错误）。
- `npm run test:web`：通过（23 个文件 / 158 个用例，含 `chatSession` 多会话新增单测）。
- `npm run build:web`：通过（Vite 产物正常，助手页 chunk 59.2 kB gzip 21.5 kB）。
- `npx playwright test`（合成 API）：37 通过 / 6 跳过（需真实后端的 `hct405-real-api`、`local-api-smoke`）/ 2 失败。
  两个失败用例（`hct418` 的「扫描质量门控到人工确认」与「空数据、未授权和服务异常都显示恢复入口」）在
  `origin/master`（dfee711）上以完全相同的方式失败——期望文案「确认候选」「需要先填写开发身份」与现有页面
  文案「确认保存」「此操作需要正式账号会话」漂移，属 PR #450/#452 回退遗留，与本 Story 改动无关，未在本
  Story 范围内私自改测试语义，留待维护者裁决。
- 回归修复：助手页全幅化后，`.view-container > *` 的卡片入场动画（`translateY(14px)`）会在入场期间于裁剪
  容器内产生 14px 纵向滚动溢出，导致 `hct418`「纵向滚动收进视口内容区」用例在动画窗口内测量时失败；已为
  `.view-container.view-assistant > *` 豁免卡片入场（页面级过渡仍在），用例恢复通过。
- `git diff --check`：通过（无空白错误）。
