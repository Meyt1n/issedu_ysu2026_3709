# HCT-459：对外时间戳补上显式 UTC 标识

- Issue：[#475](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/475)
- 需求：FR-06；NFR-03、NFR-07
- 状态：进行中（实现、契约回归与后端全量回归完成；待 PR 与维护者复核）
- 负责人：Shen-huang-123
- 复核人：仓库维护者（merge 即代表人工复核完成）
- 风险：R2（时间戳误读会让"某天完成了几项"整体错一天，且错误量随查看者设备变化）
- 相关：[MOB-143](MOB-143-近7天趋势准确性与时区语义.md)（[#230](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/230)）已在移动端做了防御性归一化，本 Story 修根因
- 允许修改：`src/api/app/schemas.py`、`tests/`、本 Story、需求追踪矩阵

## 用户价值

同一份家庭数据，在任何设备上看到的业务日归属都一致。此前时间戳不带时区标识，客户端按本机时区解释，身处不同国家的家人会看到互相矛盾的趋势。

## 缺陷

`GET .../timeline` 等接口返回的时间戳不带任何时区标识：

```json
{"occurred_at":"2026-08-26T01:56:09.834402","created_at":"2026-08-26T01:56:09"}
```

按 ECMAScript 规范，带时间但**不带**标识的 ISO 串由 `Date.parse` 按**运行环境本地时区**解释：

```text
按本地(+08)解释 -> 2026-08-25T17:56:09.853Z   业务日 = 08-25
按 UTC 解释     -> 2026-08-26T01:56:09.853Z   业务日 = 08-26
```

实测（MOB-143 联机验收）在 UTC+8 设备上，一条 `08-26 01:56 UTC` 的确认事件被显示在"昨天"。任何落在 00:00–08:00 UTC 的事件都会被算进前一个业务日，偏移量取决于查看者设备。

根因不在客户端算法：数据库列是 `DateTime(timezone=True)`，但 SQLite 取回的是 naive `datetime`，Pydantic 于是序列化出不带标识的串。写入侧已统一使用 aware UTC（全仓库无 `datetime.utcnow()`，均为 `datetime.now(UTC)`），所以只需在序列化边界把语义说清楚。

## 变更

`schemas.py` 新增：

```python
def _serialize_utc(value: datetime) -> str: ...   # naive 视为 UTC，输出 ...Z

UtcDatetime = Annotated[
    datetime,
    PlainSerializer(_serialize_utc, return_type=str, when_used="json"),
]
```

并把 65 处对外模型的 `datetime` 字段声明改为 `UtcDatetime`（机械替换，仅类体内的字段声明；导入与 helper 不变）。

关键性质：

- `when_used="json"` —— 只影响 JSON 输出。`model_dump()` 仍返回 `datetime` 对象，内部消费者与既有比较逻辑不受影响；
- 入参校验不变，`Create`/`Update` 模型仍按原样接受时间字段；
- naive 值按 UTC 解释后再 `astimezone(UTC)`，已带时区的值正常换算，输出统一以 `Z` 结尾。

## 非目标

- 不改数据库列类型与迁移（写入侧已是 aware UTC）；
- 不改客户端聚合算法（MOB-143 已实现按家庭时区分桶）；
- 不引入按用户/设备时区的展示逻辑；业务日仍由家庭时区决定。

## Given / When / Then

- Given 任意事件；When 读取时间线；Then `occurred_at`/`created_at`/`recorded_at` 均带显式标识（`Z` 或 `±HH:MM`）。
- Given 家庭、成员、风险列表与事件创建响应；When 读取；Then 其中所有日期时间字段同样带标识。
- Given 时间字段回退成 naive 串；When 跑契约测试；Then 测试失败并指出具体字段路径。
- Given 内部代码调用 `model_dump()`；When 取时间字段；Then 仍是 `datetime` 对象，不是字符串。

## 测试

`tests/contract/test_hct456_utc_timestamps.py`（5 项）：递归遍历真实响应，收集所有"看起来像日期时间"的字符串并断言每一个都带标识，覆盖家庭/成员、事件时间线、事件创建响应、风险列表；另有一项"守卫的守卫"，断言遍历器确实会拒绝 naive 串（否则测试可能空转通过）。

**已验证这些测试有牙**：把 `schemas.py` 的改动 stash 回 master 内容后，5 项中有 3 项失败，并明确报出字段路径：

```text
assert not [('$.occurred_at', '2026-08-27T02:30:04.255515'),
            ('$.recorded_at', '2026-08-27T02:30:04'),
            ('$.created_at',  '2026-08-27T02:30:04')]
```

恢复改动后 5 项全过。

## 自动验证

```text
uv run ruff check src/api tests/contract/test_hct456_utc_timestamps.py
uv run pytest tests/contract/test_hct456_utc_timestamps.py
uv run pytest --ignore=tests/browser --ignore=tests/deploy
```

本机以 Python 3.13 venv 代替 `uv`（本机未装 uv）；`--basetemp` 指向可写目录以绕开本机 `%TEMP%` 权限限制。结果：`ruff` 全绿；新增 5 项全过；全量 **1167 passed / 5 skipped / 1 failed**。

该 1 项失败为 `tests/unit/test_production_configuration_gate.py::test_production_configuration_accepts_durable_face_challenges`（`pydantic_settings` 配置校验，需要额外环境变量），`tests/deploy/` 另有 6 项需要 docker（本机无 docker）。这些在本 Story 改动前后一致失败，属本机环境既有问题。

**没有任何既有测试因本变更失败**，说明此前没有测试锁定 naive 输出格式。

## 后续

MOB-143 已在移动端加了 `normalizeServerTimestamp()` 兜底（无标识则按 UTC 解释）。本 Story 合并后该兜底成为冗余保护，可保留——它对已带标识的串是恒等操作，且能防止未来某个端点回退。

## 安全、隐私与回滚

- 仅改时间字段的序列化格式，不新增、不删除任何字段，不涉及授权判定与网络出口；
- 不记录任何健康正文；
- 回滚：revert 即恢复 naive 串。届时移动端兜底仍会按 UTC 解释，因此不会立刻产生用户可见错误，但契约仍不正确，且新增的契约测试会失败——这是有意的，用失败提醒不要长期停留在旧行为上。
