# HCT-431 授权审计关联请求追踪 ID

- Story：HCT-431
- GitHub Issue：[#295](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/295)
- FR/NFR：FR-01、NFR-03、NFR-07
- 阶段：P0-W8
- 风险等级：R1
- 当前状态：进行中
- 负责人：389883656-lgtm（后端成员）
- 复核人：后端组长/维护者

## 1. 用户价值与目标

系统已经为 HTTP 请求生成 `X-Request-ID`，健康事件也保存请求关联信息，但普通授权审计记录中的 `request_id` 可能为空。发生越权、撤权或数据访问争议时，维护者无法把审计记录与具体 API 请求快速对应。本切片将当前请求 ID 安全注入授权审计，增强可追溯性，不改变任何授权结论。

## 2. 范围与非目标

本切片实现：

1. 使用 `ContextVar` 保存请求级 ID，并在请求结束时恢复上下文，避免异步请求之间串号；
2. 授权允许和拒绝写入 `AccessAudit` 时自动记录当前请求 ID；
3. 合法的客户端请求 ID继续透传，非法或超长 ID继续由现有中间件替换为服务端生成值；
4. 补充授权成功、拒绝、自定义 ID、非法 ID和上下文隔离测试。

不做：

- 不修改授权动作、数据域、访问目的、撤权和过期判定；
- 不把健康正文写入日志或审计；
- 不修改前端、数据库结构、会话和外部网络出口。

## 3. Given / When / Then 验收

- Given 请求携带合法 `X-Request-ID` 并通过授权；When 访问审计落库；Then `AccessAudit.request_id` 与响应头一致。
- Given 请求被拒绝；When 授权审计落库；Then 仍记录对应请求 ID、拒绝结果和原因。
- Given 请求未携带或携带非法请求 ID；When 请求完成；Then 响应返回服务端生成的合法 ID，审计使用同一个 ID。
- Given 前一个请求结束；When 下一个请求开始；Then 不会串用前一个请求的 ID。

## 4. 允许修改范围

- `src/api/app/request_context.py`
- `src/api/app/main.py`、`src/api/app/security.py`
- `tests/unit/test_hct431_request_context.py`、`tests/contract/test_hct431_audit_request_id.py`
- 本 Story 与 `docs/vibe-coding/12-需求追踪矩阵.md`

## 5. 验证、风险与回滚

定向验证：

```powershell
uv run ruff check src/api/app/request_context.py src/api/app/main.py src/api/app/security.py tests/unit/test_hct431_request_context.py tests/contract/test_hct431_audit_request_id.py
uv run pytest tests/unit/test_hct431_request_context.py tests/contract/test_hct431_audit_request_id.py -q
```

风险为 R1：仅补充审计关联信息，不改变访问结果。回滚时移除请求上下文注入和 `request_id` 写入即可，既有授权链路继续工作。
