# HCT-498 Web 单一正式账号密码登录

- Issue：[#615](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/615)
- 关联：HCT-417（正式会话）、HCT-439（角色门户）、HCT-453（双端口入口锁）、HCT-423/HCT-425（保留的历史认证能力）
- FR/NFR：FR-01；NFR-01、NFR-03、NFR-04、NFR-07
- 风险等级：R3（认证入口与默认身份通道变更）
- 状态：待验收

## 1. Story

作为家庭成员或家庭管理员，我希望 Web 只出现一个正式账号密码登录方式，避免把开发 Actor ID、注册、家庭 PIN 或人脸实验能力误认为正式身份入口；登录后仍由服务端家庭事实和成员授权决定我能进入哪个门户、能查看哪些数据。

## 2. 决策与范围

- 成员前台、管理后台和 `auto` 入口共享同一个“正式账号 + 密码 + 访问用途”表单。
- 删除欢迎页的开发/演示身份、账号注册、PIN、人脸和“其他登录方式”控件；Web 不再调用这些登录端点。
- Web 业务请求只使用短期 `Authorization: Bearer` 会话。视觉质量检查、文件上传与视觉任务创建一并从直接 Actor ID 改为正式会话。
- `Settings`、`.env.example` 和 Compose 的 `ALLOW_DEV_ACTOR_HEADER` 缺省改为 `false`。旧请求头仅可由隔离测试或诊断显式开启，Web 没有对应入口。
- 保留 HCT-453 的两个端口、入口品牌和登录后入口锁；成员账号不能在管理端渲染前台，管理员账号不能在成员端渲染后台。
- 不删除 `/auth/register`、PIN、人脸后端契约、数据库表或历史凭证。注册端点仅供受控开户/脚本使用；PIN 仍可用于敏感操作二次确认。这样不会破坏数据，也可无迁移回滚。
- 本 Story 只修改桌面 Web；`APP/` 移动端登录另由 MOB Story 管理。

## 3. 非目标

- 不把双端口合并成一个入口，不改变 `Household.created_by` 或成员级授权判断。
- 不宣称当前本地短期会话已经满足互联网生产部署；密钥轮换、CSRF/同源收紧、正式部署审计仍是 HCT-417 阻断项。
- 不删除人脸凭证管理页、PIN 设置页或后端实验实现；它们不再是 Web 主登录方式。
- 不重置 `demo-parent` 或任何既有账号密码，不提交真实凭据。

## 4. 验收标准

1. 给定成员、管理员或 auto 欢迎页，页面只出现正式账号、密码、访问用途和一个登录按钮，不出现演示身份、注册、PIN、人脸或其他登录方式控件。
2. 给定有效正式账号，登录后所有业务请求携带 Bearer 且不携带 `X-Actor-Id`；视觉上传链路同样遵守。
3. 给定成员账号在成员入口或管理员账号在管理入口，登录后进入正确门户；账号与入口不匹配时会话被撤销并显示跨端指引。
4. 给定受保护请求返回 401 或会话到期，Web 清空家庭、成员、健康摘要和令牌并返回唯一登录页。
5. 给定未配置环境变量的 API/Compose，开发身份头默认关闭；显式测试夹具仍能单独开启并覆盖既有 API 契约。
6. 当前部署文档明确唯一正式登录流程，以及 `demo-parent` 正式演示账号必须通过受控脚本预置而不是在登录页注册。

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

- 风险：旧书签仍可打开两个端口，但旧 PIN/人脸登录操作说明不再适用于欢迎页；账号未预置时用户无法自行在登录页注册。
- 缓解：部署前运行受控账号/演示数据脚本；登录页给出明确“管理员分配账号”提示；后端开户契约保留。
- 回滚：无数据库迁移。revert 本 Story 提交即可恢复旧 UI 和开发默认值；PIN/人脸历史凭证与后端契约未删除，无需恢复数据。

