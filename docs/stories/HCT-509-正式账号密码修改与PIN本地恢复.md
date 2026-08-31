# HCT-509 正式账号密码修改与 PIN 本地恢复

- Issue：[#637](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/637)
- 关联：HCT-417（正式会话）、HCT-423（家庭 PIN）、HCT-428（持久化与会话轮换）、HCT-498（正式 Web 登录）
- FR/NFR：FR-01；NFR-01、NFR-03、NFR-04、NFR-07
- 风险等级：R3（认证凭据变更与全会话撤销）
- 状态：实现完成，待 PR 与维护者复核

## 1. Story

作为正式家庭账号使用者，我希望登录后可以验证当前密码并修改密码；如果忘记登录密码，我希望能用本人在同一家庭已设置的六位数字密码完成本地恢复，从而不需要删除账号、重新注册或退回开发身份入口。

## 2. 范围与契约

| 路径 | 前置条件 | 请求 | 成功结果 |
|---|---|---|---|
| `POST /api/v1/auth/change-password` | 有效 Bearer 会话 + 当前密码 | `current_password`、`new_password`（JSON body） | 更新 bcrypt 哈希、撤销 actor 的全部旧会话、返回新 `AuthSessionRead` |
| `POST /api/v1/auth/recover-password` | actor 属于指定家庭，且本人已配置该家庭 PIN | `actor_id`、`household_id`、`pin`、`new_password`（JSON body） | 更新 bcrypt 哈希、撤销 actor 的全部旧会话、返回绑定家庭的新 `AuthSessionRead` |

- 登录页账号密码方式新增“忘记密码”入口；成员前台、管理后台和 auto 入口复用同一流程。
- 登录后右上角身份区新增“修改账号密码”入口，修改成功后当前页面直接使用新会话。
- 正式注册、账号密码、PIN、人脸登录与入口锁全部保留；本 Story 不重置或硬编码任何既有账号密码。
- 本地产品没有邮件/SMS 服务。未设置本人家庭 PIN 时，页面明确提示联系家庭管理员或维护人员走受控恢复流程，不提供无验证重置。

## 3. 安全不变量

1. 密码和 PIN 只放在 HTTPS/本机 HTTP 请求体，不进入 URL、localStorage、Cookie、日志或审计正文；数据库只保存 bcrypt 哈希，Bearer 只保存 SHA-256 摘要。
2. 修改密码同时验证有效 Bearer 和当前密码；新密码与当前密码相同时返回 `PASSWORD_REUSE`。
3. 忘记密码只能用同一 actor、同一家庭的现存 PIN；账号、家庭成员关系、账号记录或 PIN 任一不匹配均做限流与 dummy bcrypt，并统一返回 `401 AUTH_FAILED`。
4. 两条成功路径都撤销该 actor 的全部活动会话，再签发一条新会话；其他设备和旧页面下次请求立即得到 401。
5. 审计只记录 `PASSWORD_CHANGE` / `PASSWORD_RECOVERY`、actor、家庭、结果和脱敏原因码，不记录密码、PIN、Bearer 或哈希。
6. 输错“当前密码”是凭据确认失败，不等于现有 Bearer 失效；Web 不触发全局 401 会话清理。

## 4. 验收标准

1. Given 已登录正式账号，When 输入正确当前密码与不同的新密码，Then 返回新会话、旧会话立即失效、旧密码不能再登录、新密码可登录。
2. Given 已登录正式账号，When 当前密码错误，Then 返回统一 401、密码不变、页面仍保留原有效会话。
3. Given 忘记密码且本人家庭 PIN 已配置，When actor、家庭、PIN 均匹配，Then 重置密码并直接进入该家庭；旧会话和旧密码失效。
4. Given 未知 actor、错误家庭、已删除成员、未配置 PIN 或错误 PIN，When 请求恢复，Then 响应均为 `401 AUTH_FAILED`，不披露哪一项存在。
5. Given 页面使用任一流程，When 检查网络请求与本地存储，Then 凭据只在 JSON body，URL、会话持久化与审计中没有密码/PIN 明文。
6. Given 原正式登录页，When 回归，Then注册、账号密码、PIN、人脸入口仍存在，成员/管理员入口锁不变。

## 5. 实现与验证证据

- 后端：`src/api/app/auth.py`、`src/api/app/routes.py`、`src/api/app/schemas.py`。
- Web：`src/web/src/components/AccountSecurityDialog.vue`、`src/web/src/views/WelcomeView.vue`、`src/web/src/store.ts`、`src/web/src/api/client.ts`。
- 后端集成：`tests/integration/test_password_recovery.py`，并回归 HCT-423/HCT-428。
- 前端单元：`src/web/src/api/client.test.ts`、`src/web/src/store.test.ts`。
- 浏览器：`tests/browser/hct453-portal-entry.spec.ts` 的忘记密码和登录后修改密码场景。

```text
uv run ruff check src/api tests migrations
uv run pytest -q tests/integration/test_password_recovery.py tests/integration/test_hct423_pin_login.py tests/safety/test_hct428_persistent_auth.py
npm run check:web
npm run test:web
npx playwright test tests/browser/hct453-portal-entry.spec.ts --config playwright.config.ts --project chromium
npm run build:web
git diff --check
```

## 6. 风险与回滚

- 风险：会话撤销范围过小会留下旧设备访问；范围过大会误伤其他 actor；恢复条件过宽会造成账号接管。
- 缓解：撤销条件只按精确 actor，恢复同时绑定 actor + household + PIN + 未删除成员关系，并覆盖旧 token、旧密码、跨 actor 和错误 PIN 回归。
- 回滚：本 Story 不新增迁移或表。revert 功能提交即可移除两个新路由和两个 Web 入口；已有账号、密码哈希、PIN、人脸凭证和正式登录契约不需要恢复数据。
