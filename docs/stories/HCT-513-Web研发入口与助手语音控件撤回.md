# HCT-513 Web 管理后台研发入口与助手语音控件撤回

- Issue：待开（本任务 agent 无 issues 权限，需维护者创建并回填）
- 关联：HCT-439（管理员五组导航）、HCT-407（模型实验室教学页）、HCT-499（演示造数页）、HCT-412（Web 助手语音输入）、HCT-418（网页 E2E）、HCT-447（侧栏唯一高亮）、HCT-455（侧栏一屏）
- FR/NFR：FR-08（本地证据助手仍保留文字问答与引用）；FR-09（家庭大屏/知识文档仍在「家庭与研发」）；NFR-07（产品面不再出现研发/演示工具入口）
- 风险等级：R2（纯前端产品面撤回；不改后端模型绑定、演示补种 API、CLI 或共享语音模块）
- 状态：实现完成，待 Issue/PR 与人工验收

## 1. Story

作为家庭管理员或成员，我希望管理后台侧栏只保留家庭照护工作台，健康助手只保留文字问答。模型实验室、演示造数、语音输入、唤醒、清空会话和助手设置不再出现在产品面上。

## 2. 产品决定

| 表面 | 撤回内容 | 保留内容 |
|---|---|---|
| 管理后台侧栏「家庭与研发」 | 「模型实验室」「演示造数」导航、命令面板入口、对应 Vue 页面 | 「家庭大屏」「知识文档」；五组导航结构不变 |
| 健康助手（Web） | 麦克风/唤醒聆听、唤醒词设置、右上角「清空会话」和「助手设置」抽屉 | 文字输入、联网搜索勾选、侧栏「开始新对话」/删线程、气泡「朗读回答」 |
| 后端 / CLI | 不改 | 模型绑定/发布阻断 API、`POST /api/v1/demo/formal-health-seed`、`scripts/seed_formal_demo_health.py` |
| 随身版 APP / 刷脸口播 | 不改 | `APP` 助手语音、`FaceVideoCapture` 采集口播、`shared/voice/` |

## 3. 与冻结规格的冲突（不得默默忽略）

- [需求规格](../vibe-coding/01-需求规格说明书.md) FR-09 / P0-10 与 [产品信息架构](../vibe-coding/18-产品信息架构与页面设计.md) 仍把「模型实验室」列为十个核心页面之一。
- HCT-412 仍把 Web 助手语音输入、唤醒词和设置抽屉写进验收。
- HCT-407 / HCT-499 仍描述对应 Vue 教学页。

本增量**不改**上述冻结正文。产品面按用户明确要求撤回入口；规格冲突记在此处，由维护者决定是否修订 FR-09/P0-10 或恢复页面。

## 4. 验收条件

1. Given 管理后台已登录；When 查看侧栏与 Ctrl+K 命令面板；Then 不出现「模型实验室」「演示造数」，「家庭大屏」「知识文档」仍在「家庭与研发」。
2. Given 打开健康助手；When 查看顶栏和输入区；Then 没有麦克风、唤醒提示、「清空会话」或齿轮设置；可用文字发送，侧栏可开始新对话。
3. Given 助手回答完成；When 点「朗读回答」；Then 仍可用本机 TTS 朗读（不自动开麦）。
4. Given 旧代码路径再访问 `modellab` / `demo-lab`；When 类型检查；Then `ViewName` 已删除这两项，无法再挂载页面。

## 5. 实现与证据

- `src/web/src/ui/navigation.ts`、`App.vue`、`store.ts`：删除导航项与视图；删除 `SHOW_ADVANCED_LAB` / `featureFlags.ts`。
- 删除 `ModelLabView.vue`、`DemoLabView.vue`、`ui/demoLab.ts(+test)`。
- `src/web/src/views/AssistantView.vue`：去掉听写/唤醒/设置/清空会话 UI 与逻辑；保留文字聊天与朗读。
- 浏览器：`tests/browser/hct405-visible-workflows.spec.ts`、`hct418-web-e2e.spec.ts`、`hct455-overview-layout.spec.ts`；单测 `navigation.test.ts`。

## 6. 回滚

恢复上述 Vue 页面、导航项和助手控件即可；后端契约、演示补种脚本和共享语音模块无需回滚。
