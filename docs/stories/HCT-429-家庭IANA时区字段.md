# HCT-429 家庭 IANA 时区字段与服务端契约

- Story：HCT-429
- GitHub Issue：[#306](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/306)
- FR/NFR：FR-06、NFR-03、NFR-07
- 阶段：P1-W8
- 风险等级：R2
- 当前状态：进行中
- 负责人：389883656-lgtm（后端成员）
- 复核人：后端组长/维护者

## 1. 用户价值与目标

移动端近 7 天趋势必须按家庭所在地的业务日统计。移动端已经按服务端提供的 IANA 时区实现了安全降级，但当前 `HouseholdRead` 没有返回 `time_zone`，联机趋势只能一直显示“不可用”。本切片补齐家庭时区的后端事实源，保证创建、读取和修改都使用合法的 IANA 时区名称。

## 2. 范围与非目标

本切片实现：

1. 为 `Household` 增加非空 `time_zone` 字段，并通过 Alembic 迁移为历史家庭回填明确的 `UTC` 基线；
2. 增加 `default_household_time_zone` 配置，创建家庭未指定时使用部署配置，而不是在路由中隐式硬编码；
3. 创建和修改家庭时校验 IANA 时区名称，读取家庭时返回 `time_zone`；
4. 新增 Owner 专用 `PATCH /api/v1/households/{household_id}`，允许修改家庭业务时区；
5. 覆盖创建、读取、更新、非法值、权限边界和迁移回归测试。

不做：

- 不修改移动端趋势算法、事件时间戳或计划折叠逻辑；
- 不引入成员级、设备级时区，也不把时区作为授权依据；
- 不使用浏览器本地时区替代服务端值；
- 不新增外部网络出口或健康数据字段。

## 3. Given / When / Then 验收

- Given 创建家庭时传入 `Asia/Shanghai`；When 读取家庭；Then 响应包含同一合法 IANA 时区。
- Given 创建家庭未传入时区；When 服务端处理请求；Then 使用 `default_household_time_zone` 配置值并持久化返回。
- Given 创建或修改时传入不存在的时区名；When 校验请求；Then 返回 422 且数据库中的原值不变。
- Given Owner 修改家庭时区；When 请求 `PATCH /households/{id}`；Then 更新成功并返回新的时区。
- Given 非 Owner 修改或读取跨家庭资源；When 请求接口；Then 保持 `404 RESOURCE_NOT_FOUND` 语义。
- Given 已有历史数据库；When 执行迁移到 head；Then `household.time_zone` 非空且既有家庭回填 `UTC`，迁移图保持单 head。

## 4. 允许修改范围

- `src/api/app/time_zone.py`、`src/api/app/config.py`
- `src/api/app/models.py`、`src/api/app/schemas.py`、`src/api/app/routes.py`
- `migrations/versions/0017_hct429_household_timezone.py`
- HCT-429 单元、契约和迁移测试
- `docs/vibe-coding/06-API设计规范.md`
- `docs/vibe-coding/12-需求追踪矩阵.md`
- 本 Story 文件

## 5. 验证、风险与回滚

定向验证：

```powershell
uv run ruff check src/api/app/time_zone.py src/api/app/config.py src/api/app/models.py src/api/app/schemas.py src/api/app/routes.py migrations/versions/0017_hct429_household_timezone.py tests/unit/test_hct429_timezone.py tests/contract/test_hct429_household_timezone_contract.py tests/integration/test_hct429_household_timezone_migration.py
uv run pytest tests/unit/test_hct429_timezone.py tests/contract/test_hct429_household_timezone_contract.py tests/integration/test_hct429_household_timezone_migration.py -q
```

风险为 R2：时区错误会让业务日整体偏移，IANA 校验和 Owner 边界必须 fail-closed。回滚时先回退 API/模型提交，再执行迁移 downgrade；回滚后移动端恢复为“时区不可用”，不得退回浏览器时区统计。
