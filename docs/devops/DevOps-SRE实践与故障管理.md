# DevOps-SRE实践与故障管理

> 本文档是家健镜系统 SRE 实践与故障管理的完整指南，覆盖 SLI/SLO、错误预算、故障管理、应急响应、事后复盘。

## 1. 概述

### 1.1 SRE 目标

1. 可用性 > 99.9%
2. 故障恢复时间 < 30 分钟
3. 变更失败率 < 1%
4. 部署频率 > 每天
5. 平均修复时间 < 1 小时

### 1.2 核心概念

| 概念 | 说明 |
| --- | --- |
| SLI | 服务等级指标，可量化的度量 |
| SLO | 服务等级目标，SLI 的目标值 |
| SLA | 服务等级协议，与用户的约定 |
| 错误预算 | 1 - SLO，允许的故障时间 |

## 2. SLI/SLO 设计

### 2.1 关键 SLI

```yaml
# SLI 定义
slis:
  - name: api_availability
    description: API 可用性
    expression: (total_requests - error_requests) / total_requests
    target: 99.9%

  - name: api_latency_p95
    description: API P95 延迟
    expression: histogram_quantile(0.95, request_duration_bucket)
    target: < 500ms

  - name: data_freshness
    description: 数据新鲜度
    expression: now() - last_data_update
    target: < 5 minutes

  - name: system_throughput
    description: 系统吞吐量
    expression: rate(requests_total[1m])
    target: > 1000 req/s
```

### 2.2 错误预算

```python
class ErrorBudget:
    def __init__(self, slo: float, period_days: int = 30):
        self.slo = slo
        self.period_days = period_days
        self.total_minutes = period_days * 24 * 60

    @property
    def budget_minutes(self) -> float:
        return self.total_minutes * (1 - self.slo)

    def calculate_remaining(self, current_availability: float) -> dict:
        consumed = self.total_minutes * (1 - current_availability)
        remaining = self.budget_minutes - consumed

        return {
            "total_budget_minutes": self.budget_minutes,
            "consumed_minutes": consumed,
            "remaining_minutes": remaining,
            "burn_rate": consumed / self.budget_minutes,
        }

    def should_freeze_changes(self, burn_rate: float) -> bool:
        # 错误预算消耗过快时冻结变更
        return burn_rate > 0.5
```

### 2.3 多窗口多燃烧率告警

```python
class MultiWindowAlert:
    def __init__(self, slo: float):
        self.slo = slo

    def check_alert(self, short_window_rate: float, long_window_rate: float) -> dict:
        # 快速燃烧率告警（1小时窗口）
        fast_burn = short_window_rate > 14.4 * (1 - self.slo)

        # 慢速燃烧率告警（6小时窗口）
        slow_burn = long_window_rate > 6 * (1 - self.slo)

        return {
            "fast_burn_alert": fast_burn,
            "slow_burn_alert": slow_burn,
            "short_window_rate": short_window_rate,
            "long_window_rate": long_window_rate,
        }
```

## 3. 故障管理

### 3.1 故障分级

| 级别 | 影响 | 响应时间 | 升级时间 |
| --- | --- | --- | --- |
| P0 | 核心功能不可用 | 5 分钟 | 15 分钟 |
| P1 | 重要功能受损 | 15 分钟 | 30 分钟 |
| P2 | 一般功能异常 | 30 分钟 | 2 小时 |
| P3 | 轻微问题 | 2 小时 | 24 小时 |

### 3.2 故障响应流程

```
故障发现
    ↓
故障确认（5分钟内）
    ↓
建立作战室（P0/P1）
    ↓
初步评估影响范围
    ↓
制定缓解方案
    ↓
执行缓解措施
    ↓
监控恢复情况
    ↓
故障恢复确认
    ↓
事后复盘（48小时内）
```

### 3.3 应急响应手册

```python
class IncidentResponse:
    def __init__(self):
        self.incident_commander = None
        self.communication_lead = None
        self.operations_lead = None

    def declare_incident(self, severity: str, description: str):
        incident = {
            "id": uuid.uuid4().hex,
            "severity": severity,
            "description": description,
            "status": "active",
            "created_at": datetime.utcnow(),
            "timeline": [],
        }

        # 通知相关人员
        self._notify_oncall(incident)

        # 创建作战室
        if severity in ["P0", "P1"]:
            self._create_war_room(incident)

        return incident

    def update_incident(self, incident_id: str, message: str):
        incident = self._get_incident(incident_id)
        incident["timeline"].append({
            "time": datetime.utcnow(),
            "message": message,
        })
        self._broadcast_update(incident)

    def resolve_incident(self, incident_id: str, resolution: str):
        incident = self._get_incident(incident_id)
        incident["status"] = "resolved"
        incident["resolved_at"] = datetime.utcnow()
        incident["resolution"] = resolution

        # 通知恢复
        self._notify_resolution(incident)

        # 安排复盘
        self._schedule_postmortem(incident)
```

## 4. 应急预案

### 4.1 数据库故障

```markdown
## 数据库连接耗尽

**症状：**
- API 返回 503
- 日志显示 "too many connections"
- 数据库 CPU 高

**处理步骤：**
1. 检查连接数：`SHOW PROCESSLIST`
2. 终止空闲连接：`KILL <id>`
3. 检查慢查询：`SHOW FULL PROCESSLIST`
4. 扩容连接池或优化慢查询
5. 如无法恢复，切换到只读副本

**回滚：**
- 恢复原配置
- 监控连接数恢复正常
```

### 4.2 缓存雪崩

```markdown
## 缓存雪崩

**症状：**
- 数据库 QPS 激增
- 响应时间变长
- 缓存命中率骤降

**处理步骤：**
1. 启用缓存降级
2. 增加缓存过期时间随机化
3. 热点数据永不过期
4. 数据库限流保护
5. 预热缓存

**预防：**
- 过期时间加随机值
- 多级缓存
- 熔断降级
```

### 4.3 消息队列积压

```markdown
## 消息队列积压

**症状：**
- 消费延迟增加
- 队列消息数持续增长
- 消费者 CPU 低

**处理步骤：**
1. 检查消费者状态
2. 增加消费者实例
3. 检查是否有有毒消息
4. 临时跳过异常消息
5. 扩容分区

**预防：**
- 消费者自动扩缩容
- 死信队列
- 监控消费延迟
```

## 5. 事后复盘

### 5.1 复盘模板

```markdown
# 故障复盘报告

## 基本信息
- 故障 ID：
- 故障级别：
- 开始时间：
- 恢复时间：
- 持续时间：
- 影响范围：

## 时间线
| 时间 | 事件 | 操作人 |
| --- | --- | --- |
| | | |

## 根因分析
### 直接原因
### 根本原因
###  contributing factors

## 影响评估
- 用户影响：
- 业务影响：
- 数据影响：

## 处理过程
- 做了什么：
- 什么有效：
- 什么无效：

## 改进措施
| 措施 | 负责人 | 截止时间 | 优先级 |
| --- | --- | --- | --- |
| | | | |

## 经验教训
```

### 5.2 无指责文化

```python
class Postmortem:
    def __init__(self):
        self.blameless = True  # 无指责原则

    def generate_report(self, incident: dict) -> dict:
        return {
            "incident_id": incident["id"],
            "summary": incident["description"],
            "timeline": incident["timeline"],
            "root_cause": self._analyze_root_cause(incident),
            "contributing_factors": self._identify_factors(incident),
            "action_items": self._generate_actions(incident),
            "lessons_learned": self._extract_lessons(incident),
        }

    def _analyze_root_cause(self, incident: dict) -> str:
        # 5 Whys 分析
        return "通过 5 Whys 分析得出的根本原因"
```

## 6. 变更管理

### 6.1 变更风险评估

```python
class ChangeRiskAssessment:
    def assess(self, change: dict) -> dict:
        risk_score = 0

        # 影响范围
        if change["scope"] == "global":
            risk_score += 3
        elif change["scope"] == "partial":
            risk_score += 2
        else:
            risk_score += 1

        # 回滚难度
        if change["rollback_difficulty"] == "hard":
            risk_score += 3
        elif change["rollback_difficulty"] == "medium":
            risk_score += 2
        else:
            risk_score += 1

        # 是否有灰度
        if not change.get("canary"):
            risk_score += 2

        return {
            "risk_score": risk_score,
            "risk_level": "high" if risk_score > 6 else "medium" if risk_score > 3 else "low",
            "requires_approval": risk_score > 3,
        }
```

### 6.2 变更冻结

```python
class ChangeFreeze:
    def __init__(self, error_budget: ErrorBudget):
        self.error_budget = error_budget

    def is_frozen(self) -> bool:
        budget_status = self.error_budget.calculate_remaining(
            current_availability=self._get_current_availability()
        )
        return budget_status["burn_rate"] > 0.9
```

## 7. SRE 检查清单

- [ ] SLI 定义
- [ ] SLO 目标
- [ ] 错误预算
- [ ] 多窗口告警
- [ ] 故障分级
- [ ] 应急响应
- [ ] 应急预案
- [ ] 事后复盘
- [ ] 无指责文化
- [ ] 变更风险评估
- [ ] 变更冻结
- [ ] 持续改进

---

*SRE 是可用性的守护者。科学的指标、快速的响应、持续的改进，让系统稳定可靠。*
