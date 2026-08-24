# HCT-428：账号、会话与 PIN 的持久化、轮换与多进程一致性

- Issue：[#297](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/297)
- 需求：FR-01；NFR-01、NFR-03、NFR-04
- 状态：进行中（Ready 后开始实现；尚无合并或验收证据）
- 负责人：Shen-huang-123
- 复核人：仓库维护者（R3 认证/迁移变更，merge 即代表人工复核完成）
- 风险：R3（会话固定、凭据泄漏、跨进程限流绕过或迁移丢失会造成越权）
- 依赖：HCT-107（#47）、HCT-423（#279）、HCT-427（#288）
- 阻塞关系：完成前，HCT-417（#258）与 MOB-133（#219）不得宣称已通过正式部署验收

## 用户价值

账号、家庭 PIN、会话、失败计数和二次确认 challenge 在 API 重启、多 worker 和多副本部署后仍保持一致；改密码、撤权、删除成员或设备丢失时可以立即撤销在线会话，而不是依赖内存状态自然过期。

## 范围

- 将账号密码哈希、家庭/成员 PIN 哈希、会话元数据、失败计数/锁定窗口和 PIN challenge 持久化到业务数据库；密码与 PIN 只保存 bcrypt 哈希，Bearer 只保存不可逆指纹/哈希，不保存明文 token。
- 保持现有 `/auth/login`、`/auth/session`、`/auth/logout`、`/auth/pin*` 请求/响应形态；若轮换产生新 token，响应仍遵循现有 `AuthSessionRead` 契约。
- 密码登录成功时按“同一身份只保留最新密码会话”策略轮换旧会话；PIN/人脸登录保留已有密码会话，避免家庭内并行登录被意外踢出；二次确认成功保持当前会话绑定（否则客户端无法消费现有 `StepUpGrantRead` 契约）。提供按会话和按家庭/身份撤销能力，并在成员删除等既有安全边界触发家庭级撤销。
- 失败次数和锁定窗口在多进程间共享，`MAX_LOGIN_ATTEMPTS` 作为全局上限生效。
- TTL、滑动续期、会话保留策略和 Cookie 传输时的 CSRF 前置条件必须配置化并写入部署文档。

## 非目标

- 不引入 OAuth/OIDC 或云端身份服务。
- 不修改移动端页面；不把 Android 真机验收混入本 Story。
- 不实现人脸识别、多家庭切换或新的医疗/风险规则。
- 不把密码、PIN、Bearer、Cookie、健康数据或原始请求正文写入日志、测试报告、Issue 或迁移默认值。

## 安全不变量

1. 数据库、日志和 API 响应中不存在密码、PIN 或 Bearer 明文。
2. 旧 token 在轮换/撤销后立即失效；过期、未知、重复和跨身份 token 统一按现有 401 语义处理。
3. 会话、失败计数和 challenge 的读改写必须具备事务/并发保护，不能依赖 Python 进程内字典。
4. 迁移必须支持空库升级、已有教学数据升级、失败恢复和向下回滚；迁移失败不得删除或覆盖现有账号/家庭数据。
5. 默认 Bearer 传输不需要 CSRF；若部署启用 Cookie，必须先满足同源/CSRF 防护和部署审计条件。

## Given / When / Then 验收条件

- Given 已注册账号、家庭 PIN 和有效 Bearer 会话，When API 进程重启，Then 账号、PIN 和会话按配置仍可验证，不能退回注册或随机 401。
- Given 两个 worker 共享同一数据库，When 使用同一 Bearer 访问受保护端点，Then 任意 worker 都能验证该会话；失败计数跨 worker 累计并在达到上限时统一返回 429。
- Given 同一身份再次密码登录，When 启用会话轮换策略，Then 新会话可用、旧密码 token 立即失效，并只记录脱敏的会话指纹和原因码；PIN/人脸会话和二次确认仍绑定并复用各自有效会话。
- Given 改密码、成员删除或授权撤销触发身份级撤销，When 该身份的旧会话再次请求，Then 全部返回 401，且不会显示旧健康数据。
- Given challenge 已过期、已使用、属于其他会话或动作不匹配，When 提交验证，Then 按现有不泄露细节的错误语义拒绝，不能重放或跨会话使用。
- Given 迁移从空库或已有教学库执行，When 执行升级、启动 API、回滚演练，Then 数据完整性、索引/外键和认证契约均有可定位证据。
- Given 使用 Cookie 传输配置，When 发起跨站写请求，Then CSRF 防护拒绝请求；Bearer 配置不增加不必要的 CSRF 例外。

## 允许修改范围

`src/api/app/auth.py`、`src/api/app/models.py`、`src/api/app/routes.py`、`src/api/app/schemas.py`、`src/api/app/security.py`、`src/api/app/config.py`、`migrations/versions/`、`tests/`、相关部署/安全文档、本 Story 和需求追踪矩阵。不得修改移动端范围或引入云端认证依赖。

## 测试与证据

- 契约/集成测试：重启后账号、PIN、会话仍有效；多 worker 会话验证一致；全局锁定；轮换与撤销；challenge 重放/跨会话拒绝；Cookie-CSRF（如配置启用）。
- 迁移测试：空库升级、已有库升级、索引/外键检查、失败恢复、向下回滚；使用虚构账号和家庭数据。
- 安全回归：日志/响应/数据库扫描不含秘密；密码/PIN/Bearer 不进入 URL、localStorage、审计正文或错误消息。
- 预期命令：`uv run ruff check src/api tests migrations`、定向认证/迁移测试、`uv run pytest`、`git diff --check`、`docker compose config --quiet`。
- 人工验收：至少两个 API worker、重启前后登录与会话、撤销后 401、迁移/回滚记录和脱敏日志抽查；不需要 Android 设备。

## 部署、回滚与已知限制

- 发布前登记代码、迁移、配置和数据库备份版本；先在教学库演练前滚与回滚，再进入受控部署。
- 回滚优先使用迁移向下路径；若发现会话一致性或凭据暴露问题，停止正式登录入口、撤销活跃会话并恢复上一版已验证组合。不得把内存认证重新当作正式部署能力。
- 当前基线仍使用进程内认证字典；本 Story 未合并前只能用于本地教学演示，不能宣称已支持多进程或正式部署。
