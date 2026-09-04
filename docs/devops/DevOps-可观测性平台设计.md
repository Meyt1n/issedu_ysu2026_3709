# DevOps-可观测性平台设计

> 本文档是家健镜系统可观测性平台的完整设计说明，覆盖日志、指标、链路追踪、告警、可视化。

## 1. 概述

### 1.1 设计目标

1. 全链路可观测：从前端到数据库全链路追踪
2. 实时告警：故障 1 分钟内发现
3. 快速定位：故障根因 5 分钟内定位
4. 数据保留：日志 7 天，指标 30 天
5. 高可用：监控系统自身可用性 99.9%

### 1.2 三大支柱

| 支柱 | 工具 | 用途 |
| --- | --- | --- |
| 日志（Logging） | ELK / Loki | 事件记录、错误排查 |
| 指标（Metrics） | Prometheus | 性能监控、趋势分析 |
| 追踪（Tracing） | Jaeger / Zipkin | 分布式链路追踪 |

## 2. 日志系统

### 2.1 日志规范

```python
import logging
import json
from datetime import datetime

class StructuredLogger:
    def __init__(self, name, service_name):
        self.logger = logging.getLogger(name)
        self.service_name = service_name

    def _format(self, level, message, **kwargs):
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': level,
            'service': self.service_name,
            'message': message,
            **kwargs,
        }
        return json.dumps(log_entry, ensure_ascii=False)

    def info(self, message, **kwargs):
        self.logger.info(self._format('INFO', message, **kwargs))

    def error(self, message, **kwargs):
        self.logger.error(self._format('ERROR', message, **kwargs))

    def warning(self, message, **kwargs):
        self.logger.warning(self._format('WARNING', message, **kwargs))
```

### 2.2 日志采集

```yaml
# Filebeat 配置
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/log/homecare/*.log
    json.keys_under_root: true
    json.add_error_key: true
    fields:
      service: homecare-backend
      environment: production

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  index: "homecare-logs-%{+yyyy.MM.dd}"

setup.template.name: "homecare-logs"
setup.template.pattern: "homecare-logs-*"
```

### 2.3 日志查询

```python
class LogQueryService:
    def __init__(self, es_client):
        self.es = es_client

    def search_logs(self, service, level, start_time, end_time, keyword=None):
        query = {
            "bool": {
                "must": [
                    {"term": {"service": service}},
                    {"term": {"level": level}},
                    {"range": {"timestamp": {"gte": start_time, "lte": end_time}}},
                ]
            }
        }

        if keyword:
            query["bool"]["must"].append({"match": {"message": keyword}})

        result = self.es.search(
            index="homecare-logs-*",
            body={"query": query, "size": 100, "sort": [{"timestamp": "desc"}]},
        )
        return result['hits']['hits']
```

## 3. 指标系统

### 3.1 Prometheus 指标

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# 请求计数
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

# 请求延迟
REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'HTTP request latency',
    ['method', 'endpoint'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0)
)

# 活跃连接
ACTIVE_CONNECTIONS = Gauge(
    'active_connections',
    'Active database connections'
)

# 中间件
@app.middleware("http")
async def metrics_middleware(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code,
    ).inc()

    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=request.url.path,
    ).observe(duration)

    return response
```

### 3.2 业务指标

```python
# 自定义业务指标
MEDICINE_ADDED = Counter('medicine_added_total', 'Total medicines added')
HEALTH_ALERT_TRIGGERED = Counter('health_alert_triggered_total', 'Total health alerts', ['level'])
USER_ACTIVE = Gauge('active_users', 'Active users')

class MetricsService:
    def record_medicine_added(self):
        MEDICINE_ADDED.inc()

    def record_health_alert(self, level):
        HEALTH_ALERT_TRIGGERED.labels(level=level).inc()

    def set_active_users(self, count):
        USER_ACTIVE.set(count)
```

### 3.3 Prometheus 配置

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'homecare-backend'
    static_configs:
      - targets: ['backend:8000']
    metrics_path: '/metrics'

  - job_name: 'homecare-app'
    static_configs:
      - targets: ['app:8080']

  - job_name: 'postgresql'
    static_configs:
      - targets: ['postgres-exporter:9187']

  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']
```

## 4. 链路追踪

### 4.1 OpenTelemetry 集成

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# 初始化
jaeger_exporter = JaegerExporter(
    agent_host_name='jaeger',
    agent_port=6831,
)

trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(jaeger_exporter)
)

# FastAPI 集成
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)

# 自定义 Span
tracer = trace.get_tracer(__name__)

@app.get("/medicines")
async def get_medicines():
    with tracer.start_as_current_span("query_database") as span:
        span.set_attribute("db.table", "medicines")
        medicines = await db.query("SELECT * FROM medicines")

    with tracer.start_as_current_span("serialize_response"):
        return [m.to_dict() for m in medicines]
```

### 4.2 跨服务传播

```python
import requests
from opentelemetry.propagate import inject

class ServiceClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def call_service(self, endpoint):
        headers = {}
        inject(headers)  # 注入 trace context

        response = requests.get(
            f"{self.base_url}/{endpoint}",
            headers=headers,
        )
        return response.json()
```

## 5. 告警系统

### 5.1 告警规则

```yaml
# alert_rules.yml
groups:
  - name: homecare-alerts
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "高错误率"
          description: "错误率超过 5%，持续 2 分钟"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "高延迟"
          description: "P95 延迟超过 1 秒"

      - alert: DatabaseDown
        expr: pg_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "数据库宕机"

      - alert: DiskSpaceLow
        expr: (node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100 < 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "磁盘空间不足"
```

### 5.2 告警通知

```python
class AlertNotifier:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url

    def send_alert(self, alert):
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"[{alert['severity']}] {alert['summary']}",
                "text": f"**{alert['summary']}**
{alert['description']}
服务: {alert.get('service', 'unknown')}",
            },
        }
        requests.post(self.webhook_url, json=message)
```

## 6. 可视化面板

### 6.1 Grafana 仪表盘

```json
{
  "dashboard": {
    "title": "家健镜系统概览",
    "panels": [
      {
        "title": "请求量",
        "type": "graph",
        "targets": [{"expr": "rate(http_requests_total[5m])"}],
      },
      {
        "title": "错误率",
        "type": "gauge",
        "targets": [{"expr": "sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))"}],
      },
      {
        "title": "P95 延迟",
        "type": "graph",
        "targets": [{"expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"}],
      },
    ],
  }
}
```

## 7. 可观测性检查清单

- [ ] 结构化日志
- [ ] 日志采集
- [ ] 日志查询
- [ ] Prometheus 指标
- [ ] 业务指标
- [ ] 链路追踪
- [ ] 跨服务传播
- [ ] 告警规则
- [ ] 告警通知
- [ ] 可视化面板
- [ ] 数据保留
- [ ] 高可用

---

*可观测性是系统健康的体检仪。日志、指标、追踪三位一体，让故障无所遁形。*
