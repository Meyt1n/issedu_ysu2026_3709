# DevOps-监控告警与可观测性平台

> 本文档是家健镜系统监控告警与可观测性平台的完整设计说明，覆盖指标监控、日志分析、链路追踪、告警管理、可视化看板。

## 1. 概述

### 1.1 设计目标

1. 监控覆盖率 100%
2. 告警响应 < 5 分钟
3. 故障定位 < 15 分钟
4. 系统可用性 > 99.9%
5. 全链路可追踪

### 1.2 可观测性三大支柱

| 支柱 | 工具 | 用途 |
| --- | --- | --- |
| Metrics（指标） | Prometheus + Grafana | 系统健康状态 |
| Logs（日志） | ELK / Loki | 问题排查 |
| Traces（链路） | Jaeger / SkyWalking | 性能分析 |

## 2. 指标监控

### 2.1 Prometheus 配置

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']

rule_files:
  - 'rules/*.yml'

scrape_configs:
  - job_name: 'backend'
    metrics_path: '/actuator/prometheus'
    static_configs:
      - targets: ['backend:8080']
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance

  - job_name: 'mysql'
    static_configs:
      - targets: ['mysqld-exporter:9104']

  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']

  - job_name: 'node'
    static_configs:
      - targets: ['node-exporter:9100']
```

### 2.2 业务指标

```python
from prometheus_client import Counter, Histogram, Gauge

class MetricsCollector:
    # 请求计数
    http_requests_total = Counter(
        'http_requests_total',
        'Total HTTP requests',
        ['method', 'endpoint', 'status']
    )

    # 请求延迟
    http_request_duration_seconds = Histogram(
        'http_request_duration_seconds',
        'HTTP request duration',
        ['method', 'endpoint'],
        buckets=[0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10]
    )

    # 活跃用户
    active_users = Gauge(
        'active_users',
        'Number of active users'
    )

    # 业务指标
    medicine_reminders_sent = Counter(
        'medicine_reminders_sent_total',
        'Total medicine reminders sent'
    )

    @classmethod
    def track_request(cls, method: str, endpoint: str, status: int, duration: float):
        cls.http_requests_total.labels(method, endpoint, str(status)).inc()
        cls.http_request_duration_seconds.labels(method, endpoint).observe(duration)
```

### 2.3 中间件集成

```python
from fastapi import Request
import time

@app.middleware('http')
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    MetricsCollector.track_request(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code,
        duration=duration,
    )
    return response
```

## 3. 告警规则

### 3.1 Prometheus 规则

```yaml
groups:
  - name: backend-alerts
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
          summary: 'High error rate detected'
          description: 'Error rate is {{ $value | humanizePercentage }} for more than 2 minutes'

      - alert: HighLatency
        expr: |
          histogram_quantile(0.99,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
          ) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: 'High P99 latency'
          description: 'P99 latency is {{ $value }}s for more than 5 minutes'

      - alert: ServiceDown
        expr: up{job="backend"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: 'Backend service is down'
          description: 'Backend service has been down for more than 1 minute'

  - name: database-alerts
    rules:
      - alert: MySQLDown
        expr: mysql_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: 'MySQL is down'

      - alert: HighConnections
        expr: mysql_global_status_threads_connected > 800
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: 'MySQL connections high'

      - alert: SlowQueries
        expr: rate(mysql_global_status_slow_queries[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: 'High slow query rate'
```

### 3.2 告警分级

| 级别 | 响应时间 | 通知方式 | 处理要求 |
| --- | --- | --- | --- |
| P0 紧急 | 5 分钟 | 电话+短信+钉钉 | 立即处理 |
| P1 重要 | 15 分钟 | 短信+钉钉 | 工作时间立即 |
| P2 一般 | 1 小时 | 钉钉 | 工作时间处理 |
| P3 提示 | 24 小时 | 邮件 | 择机处理 |

## 4. 链路追踪

### 4.1 Jaeger 集成

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter

def init_tracing(service_name: str, jaeger_host: str):
    tracer_provider = TracerProvider()

    jaeger_exporter = JaegerExporter(
        agent_host_name=jaeger_host,
        agent_port=6831,
    )

    tracer_provider.add_span_processor(
        BatchSpanProcessor(jaeger_exporter)
    )

    trace.set_tracer_provider(tracer_provider)
    return trace.get_tracer(service_name)
```

### 4.2 自动埋点

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

def instrument_app(app, engine):
    FastAPIInstrumentor.instrument_app(app)
    RequestsInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument(engine=engine)
```

### 4.3 自定义 Span

```python
tracer = trace.get_tracer(__name__)

class MedicineService:
    async def create_medicine(self, data: dict):
        with tracer.start_as_current_span('create_medicine') as span:
            span.set_attribute('medicine.name', data['name'])

            with tracer.start_as_current_span('validate_data'):
                self._validate(data)

            with tracer.start_as_current_span('save_to_db'):
                medicine = await self.repository.save(data)

            span.set_attribute('medicine.id', str(medicine.id))
            return medicine
```

## 5. 可视化看板

### 5.1 Grafana 面板

```json
{
  "dashboard": {
    "title": "家健镜系统概览",
    "panels": [
      {
        "title": "请求量",
        "type": "graph",
        "targets": [
          {
            "expr": "sum(rate(http_requests_total[5m]))",
            "legendFormat": "总请求量"
          }
        ]
      },
      {
        "title": "错误率",
        "type": "gauge",
        "targets": [
          {
            "expr": "sum(rate(http_requests_total{status=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m]))"
          }
        ]
      },
      {
        "title": "P99 延迟",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))"
          }
        ]
      },
      {
        "title": "服务状态",
        "type": "stat",
        "targets": [
          {"expr": "up"}
        ]
      }
    ]
  }
}
```

### 5.2 业务看板

| 看板 | 指标 |
| --- | --- |
| 用户看板 | DAU、MAU、新增用户、留存率 |
| 用药看板 | 提醒发送量、服药率、漏服率 |
| 问诊看板 | 问诊量、平均响应时间、满意度 |
| 商城看板 | 订单量、GMV、转化率、退款率 |
| 设备看板 | 设备在线数、数据上报量、异常设备 |

## 6. 告警管理

### 6.1 Alertmanager

```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default'
  routes:
    - match:
        severity: critical
      receiver: 'critical'
      repeat_interval: 1h
    - match:
        severity: warning
      receiver: 'warning'

receivers:
  - name: 'default'
    webhook_configs:
      - url: 'http://dingtalk-bot:8080/alert'

  - name: 'critical'
    webhook_configs:
      - url: 'http://dingtalk-bot:8080/alert'
    # 电话通知通过外部服务

  - name: 'warning'
    webhook_configs:
      - url: 'http://dingtalk-bot:8080/alert'
```

### 6.2 告警抑制

```yaml
inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'instance']
```

## 7. 监控检查清单

- [ ] Prometheus 配置
- [ ] 业务指标
- [ ] 中间件集成
- [ ] 告警规则
- [ ] 告警分级
- [ ] Jaeger 集成
- [ ] 自动埋点
- [ ] 自定义 Span
- [ ] Grafana 看板
- [ ] 业务看板
- [ ] Alertmanager
- [ ] 告警抑制

---

*完善的监控是系统稳定的保障。指标、日志、链路三位一体，让每一个问题都无所遁形。*
