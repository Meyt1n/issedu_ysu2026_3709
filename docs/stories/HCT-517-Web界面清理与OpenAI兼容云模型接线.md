# HCT-517 Web 界面清理与 OpenAI 兼容云模型接线

- Issue：[#656](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/656)
- 关联：HCT-455（总览排版）、HCT-513（研发入口收口）、HCT-516（演示入口收口）
- FR/NFR：FR-08（助手回答链路）；FR-09（总览与运行状态可读性）；NFR-02（健康数据出网边界）；NFR-04（依赖故障降级）；NFR-07（可理解的页面交互）
- 风险等级：R3（云端模型是显式健康上下文外发扩展；默认关闭；无真实密钥入库）
- 状态：进行中，待 PR、门禁和维护者人工复核

## 1. Story

作为家庭照护系统维护者，我希望 Web 页面减少重复的辅助说明、总览编号和视觉层级更清楚、滚动行为统一，同时能在独立运维配置下接入 OpenAI 兼容的云模型，以便验证不同模型服务商的兼容性；家庭默认仍保持本地优先和结构化降级。

## 2. 范围与产品决定

| 范围 | 决定 |
|---|---|
| Web 页面 | 主内容滚动容器铺满主区域，页面级滚动条落在浏览器最右侧；总览 01–05 编号放大并增加轻量图标/装饰；删除本轮指定的重复辅助文案；前端导航隐藏「授权管理」入口，但不删除后端授权 API 或现有登录/注册/忘记密码系统。 |
| 云模型 | `LLM_PROVIDER=cloud` 才启用 OpenAI 兼容 `/chat/completions`；默认 `local`，半配置或不安全地址回到本地，不增加前端开关。 |
| 响应格式 | `json_schema` 发送 OpenAI Schema 包装；`json_object` 发送 DeepSeek `{"type":"json_object"}`；`none` 不发送 `response_format`。应用层继续校验模型结果。 |
| 兼容重试 | 上游对带 `response_format` 的请求返回 400 时，移除可选响应格式重试一次；即使该请求没有 `tools` 也必须走兼容重试。确定性鉴权/模型 4xx 不循环重试。 |
| 密钥 | API key 只从本机环境读取，Authorization 仅发给配置端点；异常日志中脱敏，不提交真实密钥、健康数据或运行日志。 |

## 3. 非目标与事实冲突

- 不改变登录、注册、密码找回、Bearer 会话、家庭授权 API 或后端权限判定。
- 不把云模型作为家庭版默认回退；`llm-cloud` 能力声明仍保持不可用，云模型开关是独立运维扩展。
- 不修改随身版 APP、`src/web/react`、模型权重、真实健康数据或任何真实 API key。
- 现有 API/AI 规范强调家庭版默认本地、云端不作为默认回退；本 Story 仅记录一个显式 `LLM_PROVIDER=cloud` 扩展，并以默认关闭、HTTPS、无 UI 开关和应用层安全校验保持该边界。若要把它纳入家庭产品默认路径，必须另建 ADR/Issue。

## 4. Given / When / Then 验收

1. Given 管理后台总览；When 查看五个主要区块；Then 编号按 01→05 顺序呈现，编号清晰放大，每个区块有对应但不干扰内容的视觉元素，成员卡仍显示姓名、角色、状态签和事件数。
2. Given 任一内容较长的 Web 页面；When 页面需要滚动；Then 页面级滚动条属于铺满主区域的内容容器，位于浏览器最右侧，不出现居中的窄滚动容器；侧栏滚动条仍不可见但键盘/滚轮可用。
3. Given 管理后台或成员前台；When 查看侧栏、总览和本轮涉及页面；Then 不出现指定的重复辅助文案，且不出现前端「授权管理」导航入口；登录、注册、忘记密码入口仍可用。
4. Given `LLM_PROVIDER` 缺省或为 `local`；When 助手请求模型；Then 仍使用回环 Ollama；云端地址、模型名和 key 不出现在能力清单或前端响应中。
5. Given 显式 cloud 配置且响应模式分别为 `json_schema`、`json_object`、`none`；When 发起兼容请求；Then 请求体分别符合三档契约，非法模式在配置加载时被拒绝。
6. Given 上游对不带 tools 的带 `response_format` 请求返回 400；When 客户端重试；Then 第二次请求移除 `response_format` 并可成功返回；鉴权失败等确定性 4xx 只请求一次。
7. Given 上游错误正文或异常文本包含 API key；When 写入日志或转为结构化不可用错误；Then key 不出现，日志只保留脱敏文本，且调用方得到现有 `OLLAMA_UNAVAILABLE`/`MODEL_UNAVAILABLE` 降级路径。

## 5. 允许修改范围与证据

- Web：`src/web/src/App.vue`、`src/web/src/style.css`、`src/web/src/views/` 本轮涉及页面、`src/web/src/store.ts`、`src/web/src/ui/` 导航及其测试。
- API：`src/api/app/config.py`、`src/api/app/tool_call.py`、`src/api/app/local_agents.py`、新增 `src/api/app/cloud_llm.py`。
- 测试：`src/web/src/**/*.test.ts`、`tests/unit/test_cloud_llm_backend.py` 及本轮受入口变化影响的浏览器断言。
- 文档：本 Story、需求追踪矩阵、示例环境配置；不写入真实密钥。

## 6. 验证、部署影响与回滚

- 自动验证：`npm run check:web`、`npm run test:web`（目标 319 tests）、`npm run build:web`、`uv run pytest`、`uv run ruff check src/api tests migrations`、`git diff --check`。
- 人工验收：1280×800 总览/侧栏滚动检查；页面右侧滚动条与 01–05 视觉层级检查；登录/注册/忘记密码回归；使用假 key + MockTransport 验证三档请求体、400 重试与日志脱敏。
- 部署：默认配置无迁移、无外发；显式 cloud 需要运维在本机 `.env` 配置 HTTPS endpoint、模型名和 key，并单独评估数据外发授权。
- 回滚：revert 本 Story 提交；云模型回滚只需将 `LLM_PROVIDER` 改回 `local` 或删除 cloud 配置，不删除本地事实、授权记录或登录会话。

## 7. 已知限制

- 云模型适配器只保证 OpenAI-compatible Chat Completions 线协议；不同供应商的工具/Schema 能力仍需在其沙箱或 Mock 端点单独验收。
- 本轮前端隐藏授权入口不等于删除授权能力；若产品需要再次开放入口，应另做 UX/权限验收，不通过 URL 或隐藏按钮绕过导航治理。
