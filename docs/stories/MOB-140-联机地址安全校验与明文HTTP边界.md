# MOB-140：联机地址安全校验与明文 HTTP 边界

- Issue：[#224](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/224)
- 需求：FR-01、NFR-01、NFR-07
- 状态：进行中（地址解析、会话清理和自动检查完成；Android/受控部署证据和维护者复核待执行）
- 贡献分工：`ry12-20` 负责 URL 解析、协议/主机边界和 API Client fail-closed（50%）；`Shen-huang-123` 负责设置页错误展示、连接状态清理和回归验证（50%）
- 复核人：维护者合并时完成最终复核
- 风险：R2（错误配置可能阻断联机；放宽明文 HTTP 可能导致健康数据出网）
- 允许修改：`APP/src/views/MeView.vue`、`APP/src/stores/session.ts`、`APP/src/api/client.ts`、地址校验工具、测试、本 Story 和需求追踪矩阵

## 用户价值

家庭服务器地址在保存、启动请求和测试连接前都经过同一套边界校验：同源、家庭局域网/本机明文 HTTP 可用于受控联调，公网正式地址必须使用 HTTPS；地址变更后旧家庭状态和能力快照立即失效。

## 范围

- 只允许 HTTP(S)，拒绝 `javascript:`、`data:`、`file:` 等协议、内嵌凭据、查询参数和片段；
- 明文 HTTP 仅允许 localhost、`.local`、家庭私网 IPv4/IPv6 和 loopback/link-local；公网 HTTP fail-closed；
- HTTPS 地址交由浏览器/Android 网络栈执行证书和 CORS 校验，客户端不把 token、访问目的或健康数据拼入 URL；
- 设置页和 `ApiClient` 复用同一校验器，非法旧 localStorage 值启动时清空；
- 服务器地址变更时清理当前成员、能力快照、连接状态和 Provider 上下文，要求重新测试连接。

## Given / When / Then

- Given 同源、家庭 IPv4/IPv6、localhost 或 `.local` HTTP 地址；When 保存或测试；Then 规范化并允许受控联调。
- Given 公网 HTTP、非 HTTP(S)、凭据、查询参数或片段；When 保存或创建客户端；Then 展示可修复错误并阻止请求。
- Given 正式 HTTPS 地址；When 创建客户端；Then 保留 HTTPS 端点，证书/CORS/凭据由平台网络栈校验，不通过 URL 传递敏感信息。
- Given 地址发生变更或旧值非法；When 会话恢复或保存；Then 清理旧成员/能力/连接状态并要求重新探测。

## 实现与验证证据

- `APP/src/utils/serverUrl.ts`：协议、凭据、查询/片段、私网主机和明文 HTTP 边界。
- `APP/src/stores/session.ts`：启动时归一化并清理不可信旧配置。
- `APP/src/api/client.ts`：构造请求客户端前 fail-closed，暴露可识别的 `INVALID_SERVER_URL`。
- `APP/src/views/MeView.vue`：保存/测试连接校验、错误提示和状态清理。
- `APP/src/utils/serverUrl.test.ts`、`APP/src/api/client.test.ts`：同源、家庭 IPv4/IPv6、HTTPS、公网 HTTP、恶意协议和凭据回归。
- 自动检查：`npm run check`、`npm run test`、`npm run build`、`npm run android:sync`、`git diff --check`。
- Android 明文 HTTP、HTTPS 证书/CORS 和受控部署仍需维护者在目标设备/环境验收，未将本地规则测试当作生产证明。

## 回滚

PR 未合并前关闭分支；合并后回退本 PR，恢复显式联调配置入口并保留安全警告，不涉及服务器证书、网络策略或数据库迁移。
