# DevOps-监控告警与值班体系

> 本文档是家健镜系统监控告警与值班体系的完整设计说明，覆盖监控指标、告警规则、值班流程、应急响应、事后复盘。

## 1. 概述

### 1.1 设计目标

1. 故障发现 < 1 分钟
2. 告警响应 < 5 分钟
3. 故障恢复 < 30 分钟
4. 告警准确率 > 90%
5. 值班流程标准化

### 1.2 监控层级

| 层级 | 监控内容 | 工具 |
| --- | --- | --- |
| 基础设施 | CPU、内存、磁盘、网络 | Node Exporter |
| 容器 | 容器状态、资源使用 | cAdvisor |
| 应用 | QPS、延迟、错误率 | Prometheus |
| 业务 | 用户量、订单量、转化率 | 业务指标 |
| 端到端 | 用户体验、可用性 | 黑盒监控 |

## 2. 监控指标

### 2.1 黄金信号

```python
class GoldenSignals:
    # 延迟
    LATENCY = "http_request_duration_seconds"
    # 流量
    TRAFFIC = "http_requests_total"
    # 错误
    ERRORS = "http_requests_total{status=~'5..'}"
    # 饱和度
    SATURATION = "process_resident_memory_bytes"
```

### 2.2 RED 指标

```python
class REDMetrics:
    # Rate：请求速率
    RATE = "rate(http_requests_total[5m])"
    # Errors：错误率
    ERRORS = "rate(http_requests_total{status=~'5..'}[5m])"
    # Duration：延迟分布
    DURATION = "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"
```

### 2.3 USE 方法

```python
class USEMetrics:
    # Utilization：利用率
    UTILIZATION = "node_cpu_seconds_total"
    # Saturation：饱和度
    SATURATION = "node_load1"
    # Errors：错误
    ERRORS = "node_network_receive_errs_total"
```

### 2.4 业务指标

```python
class BusinessMetrics:
    # 用户指标
    DAU = "daily_active_users"
    MAU = "monthly_active_users"
    NEW_USERS = "new_users_total"

    # 交易指标
    ORDERS = "orders_total"
    REVENUE = "revenue_total"
    CONVERSION_RATE = "conversion_rate"

    # 健康指标
    MEDICATION_ADHERENCE = "medication_adherence_rate"
    HEALTH_ALERTS = "health_alerts_total"
```

## 3. 告警规则

### 3.1 Prometheus 告警

```yaml
groups:
  - name: homecare-alerts
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
          /
          sum(rate(http_requests_total[5m]))
          > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "高错误率"
          description: "错误率超过 5%，持续 2 分钟"

      - alert: HighLatency
        expr: |
          histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
          > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "高延迟"
          description: "P95 延迟超过 1 秒"

      - alert: ServiceDown
        expr: up{job="homecare-backend"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "服务宕机"
          description: "服务 {{ $labels.instance }} 不可用"

      - alert: HighCPU
        expr: |
          100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
          > 80
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "CPU 使用率高"
          description: "CPU 使用率超过 80%"

      - alert: DiskSpaceLow
        expr: |
          (node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100
          < 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "磁盘空间不足"
          description: "磁盘可用空间低于 10%"
```

### 3.2 告警分级

| 级别 | 响应时间 | 通知方式 | 处理要求 |
| --- | --- | --- | --- |
| P0 紧急 | 5 分钟 | 电话+短信+微信 | 立即处理 |
| P1 重要 | 15 分钟 | 短信+微信 | 工作时间立即 |
| P2 一般 | 30 分钟 | 微信 | 工作时间处理 |
| P3 提示 | 2 小时 | 邮件 | 择机处理 |

### 3.3 告警抑制

```yaml
# Alertmanager 配置
route:
  receiver: default
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

  routes:
    - match:
        severity: critical
      receiver: oncall
      group_wait: 10s
      repeat_interval: 1h

    - match:
        severity: warning
      receiver: dev-team
      group_wait: 1m

inhibit_rules:
  - source_match:
      severity: critical
    target_match:
      severity: warning
    equal: ['alertname', 'cluster']
```

## 4. 值班体系

### 4.1 值班排班

```python
class OnCallScheduler:
    def __init__(self, team_members: list):
        self.team_members = team_members
        self.schedule = {}

    def generate_schedule(self, start_date, weeks: int = 4):
        schedule = {}
        for week in range(weeks):
            primary = self.team_members[week % len(self.team_members)]
            secondary = self.team_members[(week + 1) % len(self.team_members)]
            schedule[start_date + timedelta(weeks=week)] = {
                'primary': primary,
                'secondary': secondary,
            }
        return schedule

    def get_oncall(self, date) -> dict:
        return self.schedule.get(date, {})
```

### 4.2 值班交接

```python
class ShiftHandover:
    def __init__(self):
        self.handover_notes = []

    def create_handover(self, outgoing: str, incoming: str, notes: dict):
        handover = {
            'outgoing': outgoing,
            'incoming': incoming,
            'time': datetime.now(),
            'open_issues': notes.get('open_issues', []),
            'pending_tasks': notes.get('pending_tasks', []),
            'special_notes': notes.get('special_notes', ''),
        }
        self.handover_notes.append(handover)
        return handover

    def get_recent_handover(self) -> dict:
        return self.handover_notes[-1] if self.handover_notes else {}
```

### 4.3 值班职责

```markdown
## 值班工程师职责

### 日常职责
- 监控告警，及时响应
- 处理 P0/P1 故障
- 记录故障处理过程
- 值班结束后交接

### 故障处理
- 5 分钟内响应 P0 告警
- 15 分钟内响应 P1 告警
- 建立作战室（P0/P1）
- 协调相关人员处理

### 交接内容
- 当前未解决问题
- 进行中的变更
- 待处理任务
- 特殊注意事项
```

## 5. 应急响应

### 5.1 故障响应流程

```
告警触发
    ↓
值班确认（5分钟内）
    ↓
评估影响范围
    ↓
P0/P1？→ 是 → 建立作战室
    ↓
制定缓解方案
    ↓
执行缓解
    ↓
监控恢复
    ↓
确认恢复
    ↓
事后复盘（48小时内）
```

### 5.2 作战室

```python
class WarRoom:
    def __init__(self, incident_id: str):
        self.incident_id = incident_id
        self.participants = []
        self.timeline = []
        self.actions = []

    def add_participant(self, name: str, role: str):
        self.participants.append({'name': name, 'role': role})

    def add_timeline_event(self, event: str):
        self.timeline.append({
            'time': datetime.now(),
            'event': event,
        })

    def add_action(self, action: str, owner: str):
        self.actions.append({
            'action': action,
            'owner': owner,
            'status': 'pending',
            'time': datetime.now(),
        })
```

### 5.3 故障升级

```python
class EscalationPolicy:
    def __init__(self):
        self.levels = [
            {'level': 1, 'role': '值班工程师', 'timeout': 5},
            {'level': 2, 'role': '技术负责人', 'timeout': 15},
            {'level': 3, 'role': '架构师', 'timeout': 30},
            {'level': 4, 'role': 'CTO', 'timeout': 60},
        ]

    def should_escalate(self, incident_duration: int, current_level: int) -> bool:
        if current_level >= len(self.levels):
            return False
        return incident_duration > self.levels[current_level]['timeout']
```

## 6. 事后复盘

### 6.1 复盘模板

```markdown
# 故障复盘报告

## 基本信息
- 故障 ID：
- 故障级别：P0/P1/P2/P3
- 开始时间：
- 恢复时间：
- 持续时间：
- 值班人员：
- 参与人员：

## 故障时间线
| 时间 | 事件 | 操作人 |
| --- | --- | --- |

## 影响评估
- 用户影响：
- 业务影响：
- 数据影响：
- 经济损失：

## 根因分析
### 直接原因
### 根本原因
###  contributing factors

## 处理过程
- 做了什么：
- 什么有效：
- 什么无效：
- 延迟原因：

## 改进措施
| 措施 | 负责人 | 截止时间 | 优先级 |
| --- | --- | --- | --- |

## 经验教训
```

### 6.2 5 Whys 分析

```python
class FiveWhys:
    def __init__(self, problem: str):
        self.problem = problem
        self.whys = []

    def add_why(self, why: str, answer: str):
        self.whys.append({'why': why, 'answer': answer})

    def get_root_cause(self) -> str:
        if self.whys:
            return self.whys[-1]['answer']
        return self.problem
```

## 7. 告警优化

### 7.1 告警降噪

```python
class AlertNoiseReducer:
    def __init__(self):
        self.alert_history = []

    def is_duplicate(self, alert: dict) -> bool:
        # 检查是否是重复告警
        for recent in self.alert_history[-10:]:
            if (recent['alertname'] == alert['alertname'] and
                recent['instance'] == alert['instance'] and
                (datetime.now() - recent['time']).total_seconds() < 300):
                return True
        return False

    def should_alert(self, alert: dict) -> bool:
        # 告警准确率低的暂时静默
        if alert['alertname'] in self._noisy_alerts():
            return False
        return not self.is_duplicate(alert)
```

### 7.2 告警质量评估

```python
class AlertQualityMetrics:
    def __init__(self):
        self.metrics = {
            'total_alerts': 0,
            'actionable_alerts': 0,
            'false_positives': 0,
            'duplicate_alerts': 0,
        }

    def record_alert(self, alert: dict, actionable: bool):
        self.metrics['total_alerts'] += 1
        if actionable:
            self.metrics['actionable_alerts'] += 1
        else:
            self.metrics['false_positives'] += 1

    @property
    def signal_to_noise_ratio(self) -> float:
        total = self.metrics['total_alerts']
        return self.metrics['actionable_alerts'] / total if total else 0
```

## 8. 监控值班检查清单

- [ ] 黄金信号
- [ ] RED 指标
- [ ] USE 方法
- [ ] 业务指标
- [ ] 告警规则
- [ ] 告警分级
- [ ] 告警抑制
- [ ] 值班排班
- [ ] 值班交接
- [ ] 应急响应
- [ ] 事后复盘
- [ ] 告警降噪

---

*完善的监控值班体系是系统稳定的保障。及时发现、快速响应、持续改进，让系统运行无忧。*
