# HCT-511 成员前台管理员门禁与 PIN 选人

- Issue：待开（本任务 agent 无 issues 权限，需维护者创建并回填）
- 关联：HCT-417（正式会话）、HCT-423（PIN 后端）、HCT-425（人脸 1:N）、HCT-439（门户分流）、HCT-453（双端口入口锁）、HCT-498 / ADR-0008、HCT-510（登录收口）
- FR/NFR：FR-01（账号密码加 PIN 二次确认）；NFR-01、NFR-07
- 风险等级：R3（认证入口与入口锁行为变更；PIN 仍按家庭+身份绑定，不把管理员会话渲染成前台）
- 状态：实现完成，待 Issue/PR 与维护者人工验收

后台「人脸凭证」已改名为「登录设置」。管理员注册并创建家庭后自动进入该页：第一步给每位家人（含管理员）设 PIN，第二步可选录入人脸。

## 1. Story

作为家庭管理员，我希望登录后台后这台电脑自动绑定当前家庭；作为家人，我希望打开成员前台时可以直接刷脸，或用 PIN 选择家人进入。

## 2. 产品决定

| 入口 | 登录方式 |
|---|---|
| 管理后台（8081 / 5174） | 家庭管理员正式账号密码。登录后自动把当前家庭绑定到这台电脑（含可 PIN 登录的家人名单）。注册后进入「登录设置」设 PIN，可选录入人脸。 |
| 成员前台（8080 / 5173） | **刷脸进入**（本机已绑定家庭且 1:N 成功）；或 **PIN 登录**（从本机绑定的家人名单中选人，输入该成员六位数字）。成功后签发**该成员**的 Bearer 会话，不渲染管理后台。 |

明确不做：

- 不把管理员会话当成成员前台身份（选人后必须换成成员会话）。
- 不删除 `/auth/pin-login`、找回密码或逐步确认。
- 不在未登录时公开家庭成员名单。
- 不改 `APP/` 移动端登录。
- 不宣称人脸为生产级生物识别。

## 3. 与既有事实源的冲突（不得默默忽略）

| 事实源 | 原决定 | 本 Story |
|---|---|---|
| [HCT-453](HCT-453-前后台分端口登录入口.md) / [ADR-0006](../decisions/0006-前后台分端口登录入口.md) | 管理员账号在成员前台立即登出并指引去后台 | 成员前台不再用管理员账号做门禁。后台入口仍拒绝纯成员账号。管理员登录后台时自动绑定本机家庭。 |
| [HCT-510](HCT-510-Web登录收口与PIN入口撤回.md) | PIN 不是 Web 登录页签 | PIN 重新作为成员前台第一层页签（与刷脸并列）；不再用管理员账号密码做前台门禁。刷脸仍可跳过 PIN。 |
| [HCT-498](HCT-498-Web单一正式账号密码登录.md) / ADR-0008 | 成员可用自己的正式账号密码进入前台 | 成员前台欢迎页改为刷脸 / PIN 选人。成员本人账号密码仍可作为兼容路径（`connectWithPassword` 与 auto 入口），产品主路径是绑定设备上的 PIN 选人或刷脸。 |
| FR-01 | 账号密码加 PIN 二次确认；P0 不以人脸为身份入口 | 成员前台主路径是 PIN 选人或刷脸。人脸跳过路径仍覆盖 FR-01 字面要求，冲突继续记在 HCT-510 / 本 Story，不改规格正文。 |

## 4. 范围

允许修改：

- `src/api/app/schemas.py`、`routes.py`：管理员可为家庭成员设置 PIN（`PinSetRequest.actor_id` 可选）；Owner 可查询 `GET /households/{id}/pin-status`
- `src/web/src/store.ts`、`WelcomeView.vue`、`FaceCredentialView.vue`、`api/client.ts`
- 对应单元、契约、浏览器测试、README、本 Story、需求追踪矩阵、HCT-510 交叉说明

## 5. 验收标准

1. Given 成员前台且本机已由管理后台绑定家庭，When 打开 PIN 登录并选择家人、输入正确 PIN，Then 进入该成员前台，不渲染管理后台，也不再要求管理员账号密码。
2. Given 成员前台，When 刷脸且本机已绑定家庭并识别成功，Then 直接进入对应成员，不经过 PIN。
3. Given 管理后台，When 管理员登录（或切换当前家庭），Then 这台电脑自动绑定该家庭及可 PIN 的家人名单；登录设置页不再展示「绑定这台电脑」勾选。
4. Given 管理后台，When 管理员为某位有登录名的家人保存六位 PIN，Then `/auth/pin` 写入该 `actor_id`；非 owner 不能给他人设 PIN。第一次保存后该行锁定为「已设置 / 修改」，页面不回显数字；只有点「修改」才能再次提交。`GET /households/{id}/pin-status` 只返回已配置的 `actor_id`，不含哈希。
5. Given 管理后台，When 纯成员账号登录，Then 仍登出并指引去成员前台（入口锁不削弱）。
6. Given 成员前台建家，When 创建者成为 owner，Then 仍提示去管理后台设置，不把建家后的管理员会话留在前台。
7. Given 成员前台且本机未绑定家庭，When 打开欢迎页，Then 不展示刷脸采集与 PIN 选人，而是提示去管理后台注册或登录管理员账号。

## 6. 验证命令

```text
npm run test:web
npx playwright test tests/browser/hct453-portal-entry.spec.ts tests/browser/hct423-pin-portal.spec.ts tests/browser/hct425-welcome-face-binding.spec.ts
uv run pytest tests/integration/test_hct423_pin_login.py tests/integration/test_hct511_owner_set_member_pin.py -q
```

## 7. 回滚

revert 本 Story 提交。无新迁移。PIN 表与 `/auth/pin-login` 仍在。入口锁恢复为「管理员在成员前台立即登出」。
