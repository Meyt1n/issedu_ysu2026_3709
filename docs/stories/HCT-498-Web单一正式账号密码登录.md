# HCT-498 Web 单一正式账号密码登录

- Issue：[#615](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/615)
- 关联：HCT-417（正式会话）、HCT-439（角色门户）、HCT-453（双端口入口锁）、HCT-423/HCT-425（保留的历史认证能力）
- FR/NFR：FR-01；NFR-01、NFR-03、NFR-04、NFR-07
- 风险等级：R3（认证入口与默认身份通道变更）
- 状态：待验收

## 1. Story

作为家庭成员或家庭管理员，我希望 Web 不再出现开发 Actor ID 演示入口，但仍能通过正式账号密码、已配置的家庭 PIN 或人脸凭证登录，并能在正式账号密码方式下完成本地注册；登录后仍由服务端家庭事实和成员授权决定我能进入哪个门户、能查看哪些数据。

## 2. 决策与范围

- 成员前台、管理后台和 `auto` 入口共享同一个正式会话；成员前台保留账号密码、PIN、人脸三种正式认证方式，管理后台默认展示账号密码。
- 删除欢迎页的开发/演示身份入口；账号注册、PIN、人脸和“其他方式”属于正式认证/开户能力，继续由 Web 按对应端点调用。
- Web 业务请求只使用短期 `Authorization: Bearer` 会话。视觉质量检查、文件上传与视觉任务创建一并从直接 Actor ID 改为正式会话。
- `Settings`、`.env.example` 和 Compose 的 `ALLOW_DEV_ACTOR_HEADER` 缺省改为 `false`。旧请求头仅可由隔离测试或诊断显式开启，Web 没有对应入口。
- 保留 HCT-453 的两个端口、入口品牌和登录后入口锁；成员账号不能在管理端渲染前台，管理员账号不能在成员端渲染后台。
- 不删除 `/auth/register`、PIN、人脸后端契约、数据库表或历史凭证。注册端点由正式登录页显式触发并受服务端限流，PIN 仍可用于敏感操作二次确认。
- 本 Story 只修改桌面 Web；`APP/` 移动端登录另由 MOB Story 管理。

## 3. 非目标

- 不把双端口合并成一个入口，不改变 `Household.created_by` 或成员级授权判断。
- 不宣称当前本地短期会话已经满足互联网生产部署；密钥轮换、CSRF/同源收紧、正式部署审计仍是 HCT-417 阻断项。
- 不删除人脸凭证管理页、PIN 设置页或后端实验实现；它们不再是 Web 主登录方式。
- 不重置 `demo-parent` 或任何既有账号密码，不提交真实凭据。

## 4. 验收标准

1. 给定成员、管理员或 auto 欢迎页，页面不出现开发/演示身份；成员前台可选择正式账号密码、PIN 或人脸，账号密码方式提供“注册本地账号”，管理员入口至少提供正式账号密码。
2. 给定有效正式账号，登录后所有业务请求携带 Bearer 且不携带 `X-Actor-Id`；视觉上传链路同样遵守。
3. 给定成员账号在成员入口或管理员账号在管理入口，登录后进入正确门户；账号与入口不匹配时会话被撤销并显示跨端指引。
4. 给定受保护请求返回 401 或会话到期，Web 清空家庭、成员、健康摘要和令牌并返回唯一登录页。
5. 给定未配置环境变量的 API/Compose，开发身份头默认关闭；显式测试夹具仍能单独开启并覆盖既有 API 契约。
6. 当前部署文档明确正式会话与各认证方式的边界；`demo-parent` 仍通过受控脚本预置，普通正式账号可从登录页进入注册流程。

## 5. 实现证据

- 唯一登录页：`src/web/src/views/WelcomeView.vue`、`src/web/src/ui/portalEntry.ts`。
- 正式会话状态与 401 清理：`src/web/src/store.ts`、`src/web/src/api/client.ts`。
- 视觉链路 Bearer 收口：`src/web/src/vision/VisionQualityPanel.vue`、`src/web/src/vision/qualityView.ts`。
- 默认关闭开发身份：`src/api/app/config.py`、`.env.example`、`docker-compose.yml`、`docker/web.Dockerfile`。
- 单元与浏览器证据：`store.test.ts`、`portalEntry.test.ts`、`qualityView.test.ts`、`tests/browser/hct417-web-session.spec.ts`、`hct423-pin-portal.spec.ts`、`hct425-welcome-face-binding.spec.ts`、`hct453-portal-entry.spec.ts`。

## 6. 验证命令

```text
npm run check:web
npm run test:web
npx playwright test tests/browser/hct417-web-session.spec.ts tests/browser/hct423-pin-portal.spec.ts tests/browser/hct425-welcome-face-binding.spec.ts tests/browser/hct453-portal-entry.spec.ts tests/browser/hct455-overview-layout.spec.ts
npx playwright test tests/browser/hct409-accessibility.spec.ts tests/browser/hct418-web-e2e.spec.ts tests/browser/hct439-member-portal.spec.ts tests/browser/hct405-visible-workflows.spec.ts tests/browser/hct416-vision-review.spec.ts
npm run build:web
uv run pytest tests/integration/test_hct417_web_session.py tests/safety/test_hct107_local_auth.py tests/unit/test_production_configuration_gate.py -q
docker compose config --quiet
git diff --check
```

## 7. 风险与回滚

- 风险：PIN/人脸需要已配置的家庭凭证和本机能力，注册仍受账号唯一性、限流和家庭建档约束。
- 缓解：开发身份头继续关闭；页面明确区分正式账号密码、PIN、人脸和注册状态；部署前仍可运行受控账号/演示数据脚本。
- 回滚：无数据库迁移。revert 本 Story 提交即可恢复旧 UI 和开发默认值；PIN/人脸历史凭证与后端契约未删除，无需恢复数据。

## 8. 需求澄清修订（2026-08-31）

用户澄清“删除演示登录”仅指删除开发 Actor ID/演示身份入口，不指删除正式认证系统。原实现过度收窄了 Web UI，误删了正式注册入口并隐藏了成员前台 PIN/人脸登录；本修订恢复这些正式能力，同时保留 Bearer 会话、入口锁和 `ALLOW_DEV_ACTOR_HEADER=false`。

## 9. HCT-510 登录收口（2026-08-31）

HCT-510 再次调整 Web 登录面：成员前台保留刷脸与账号密码，**撤回 PIN 作为欢迎页登录方式**；管理后台只保留账号密码。PIN 后端与 HCT-509 找回密码继续有效。详见 [HCT-510](HCT-510-Web登录收口与PIN入口撤回.md)。

