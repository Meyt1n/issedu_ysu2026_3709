# HCT-510 Web 登录收口与 PIN 入口撤回

- Issue：待开（本任务 agent 无 issues 权限，需维护者创建并回填）
- 关联：HCT-417（正式会话）、HCT-423（PIN 后端）、HCT-425（人脸 1:N）、HCT-427（逐步确认）、HCT-453（双端口入口锁）、HCT-456（进入指引）、HCT-498（正式 Web 认证）、HCT-509（PIN 找回密码）
- FR/NFR：FR-01；NFR-07（可理解的家庭级交互）；支撑 NFR-01
- 风险等级：R2（认证入口 UX；不改后端契约、会话签发或授权判定）
- 状态：实现与自动验证完成，待维护者合并复核

## 1. Story

作为家庭成员或家庭管理员，我希望打开成员前台或管理后台时立刻知道怎么登录，而不被三种凭据、访问用途代码和三步教程挡住。成员前台在本机已绑定家庭时用刷脸进入，否则用账号密码；管理后台只用账号密码。六位数字密码不再出现在登录页，只用于忘记密码恢复和登录后的逐步确认。

## 2. 产品决定

| 入口 | 登录方式 |
|---|---|
| 成员前台（8080 / 5173） | 本机已绑定家庭：默认刷脸 1:N；未绑定：默认账号密码。保留「刷脸进入 / 账号密码」两个页签。 |
| 管理后台（8081 / 5174） | 仅账号密码，无凭据页签 |
| auto（`npm run dev:web`） | 仅账号密码，主按钮「登录家庭空间」（保持 HCT-409 键盘/e2e） |

PIN **不是** Web 登录方式。PIN 继续用于：

- HCT-509 忘记密码本地恢复（登录页「忘记密码」）
- HCT-427 登录后敏感操作逐步确认
- 管理人脸凭证页的「找回密码用的数字密码」设置

访问用途代码从登录表单隐藏，请求仍固定发送 `family-care`。成员前台不再展示 HCT-456 三步进入清单、`formal-login-method` 横幅、长身份说明和端口号。

## 3. 与 FR-01 / HCT-498 的冲突（不得默默忽略）

[需求规格 FR-01](../vibe-coding/01-需求规格说明书.md) 写明：「账号密码加 PIN 或二维码二次确认；**P0 不以人脸为身份入口**。」

HCT-425 已将家庭内 1:N 刷脸作为成员前台登录能力合并进仓库。HCT-498 / ADR-0008 曾把 PIN/人脸从 Web 主登录撤回，后又按需求澄清恢复成员前台 PIN/人脸。本 Story 由产品负责人确认：

1. **成员前台保留刷脸登录**（覆盖 FR-01「P0 不以人脸为身份入口」在 Web 成员入口上的字面要求）。人脸仍属本地教学演示能力，不是生产级生物识别，失败时回退账号密码。
2. **PIN 不再作为 Web 登录入口**（覆盖 HCT-498 修订中「成员前台已配置 PIN 登录」的 UI 决定）。`POST /auth/pin-login`、PIN 表和契约测试全部保留，不删除。
3. 本 PR **不改写** FR-01 正文。冲突记录在本 Story 与需求追踪矩阵；是否修订规格由项目负责人另开任务。

二次确认、授权目的约束、入口锁和 Bearer 会话不变。

## 4. 范围与非目标

允许修改：

- `src/web/src/views/WelcomeView.vue`、`FaceCredentialView.vue`
- `src/web/src/ui/portalEntry.ts`、`welcomeFaceBinding.ts`、`faceCaptureGuidance.ts`
- `src/web/src/components/FaceVideoCapture.vue`、`src/web/src/store.ts` 用户可见失败回退文案
- 对应单元测试、浏览器回归、README、本 Story、需求追踪矩阵

明确不做：

- 不删除 `/auth/pin`、`/auth/pin-login`、`/auth/recover-password`、PIN 表或后端契约测试
- 不改变 HCT-453 入口锁公式、Bearer 会话或服务端授权
- 不改 `APP/` 移动端登录
- 不重置演示账号密码
- 不把人脸宣称成生产级身份认证
- 不在本 PR 改写 FR-01 规格正文

## 5. 验收标准

1. Given 成员前台且本机未绑定家庭，When 打开欢迎页，Then 默认「账号密码」，可见「刷脸进入 / 账号密码」，没有「数字密码」页签、访问用途字段和三步进入清单；主按钮文案为「进入前台」（不得与「刷脸进入」子串混淆）。
2. Given 成员前台且本机已绑定家庭并具备 `face-recognition-local`，When 打开欢迎页，Then 默认「刷脸进入」并自动打开摄像头；刷脸失败提示改用账号密码，不提示数字密码。
3. Given 管理后台，When 打开欢迎页，Then 只有账号密码表单，主按钮为「进入管理后台」，没有凭据页签。
4. Given auto 入口 `/`，When 仅用键盘，Then 焦点顺序为正式账号 → 密码 → 「登录家庭空间」。
5. Given 账号与入口不匹配，When 登录，Then 短提示「这是成员前台。当前账号是管理员，请改用管理后台。」或「这是管理后台。当前账号是家庭成员，请改用成员前台。」，链接为「去管理后台 / 去成员前台」，文案不含端口号。
6. Given 忘记密码，When 打开恢复表单，Then 仍使用「本人六位数字密码」走 `/auth/recover-password`。
7. Given 人脸凭证页，When 注册人脸，Then 只用账号密码二次确认；PIN 卡片标题为找回密码用途，不是登录方式。

## 6. 实现与验证证据

- 品牌与冲突文案：`src/web/src/ui/portalEntry.ts`
- 欢迎页：`src/web/src/views/WelcomeView.vue`
- 人脸绑定摘要：`src/web/src/ui/welcomeFaceBinding.ts`
- 采集引导与摄像头回退：`src/web/src/ui/faceCaptureGuidance.ts`、`src/web/src/components/FaceVideoCapture.vue`
- 失败桶回退：`src/web/src/store.ts` `formatError`
- 凭证页：`src/web/src/views/FaceCredentialView.vue`
- 单元：`portalEntry.test.ts`、`welcomeFaceBinding.test.ts`、`faceCaptureGuidance.test.ts`、`store.test.ts`
- 浏览器：`hct453-portal-entry.spec.ts`、`hct423-pin-portal.spec.ts`、`hct425-welcome-face-binding.spec.ts`、`hct409-accessibility.spec.ts`、`hct405-real-api.spec.ts`

```text
npm run check:web
npm run test:web
npx playwright test tests/browser/hct409-accessibility.spec.ts tests/browser/hct417-web-session.spec.ts tests/browser/hct423-pin-portal.spec.ts tests/browser/hct425-welcome-face-binding.spec.ts tests/browser/hct453-portal-entry.spec.ts --config playwright.config.ts --project chromium
npm run build:web
```

本环境验证（2026-08-31）：

- `npm run check:web`：通过
- `npm run test:web`：29 files / 267 tests passed
- Playwright chromium 上述 5 个 spec：27 passed
- `npm run build:web`：通过


## 7. 风险与回滚

- 风险：成员在未绑定本机家庭时找不到刷脸入口；管理员误进成员前台仍会被入口锁拦住；隐藏访问用途后，非 `family-care` 的授权目的无法在登录页改填（请求固定 `family-care`）。
- 缓解：未绑定默认账号密码并保留刷脸页签说明；冲突页给出另一入口链接；授权交接文案仍含用途代码，作为已知后续项。
- 回滚：无数据库迁移。revert 本 Story 提交即可恢复旧欢迎页文案与 PIN 登录页签；PIN/人脸后端与历史凭证不需要恢复数据。

## 8. HCT-511 后续修订（2026-08-31）

产品确认成员前台改为刷脸或 PIN 选人；本机未绑定家庭时不进入这两种登录页，只提示去管理后台注册或登录。入口锁对**纯成员账号进管理后台**不变。详见 [HCT-511](HCT-511-成员前台管理员门禁与PIN选人.md)。
