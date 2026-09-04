# DevOps-日志聚合与分析平台

> 本文档是家健镜系统日志聚合与分析平台的完整设计说明，覆盖日志采集、日志存储、日志查询、日志分析、告警规则。

## 1. 概述

### 1.1 设计目标

1. 日志采集延迟 < 5秒
2. 支持每秒 10万条日志
3. 日志保留 7 天热数据
4. 全文检索响应 < 1秒
5. 异常日志自动告警

### 1.2 日志架构

| 组件 | 工具 | 职责 |
| --- | --- | --- |
| 采集 | Filebeat / Fluentd | 收集日志 |
| 传输 | Kafka / Logstash | 缓冲和转换 |
| 存储 | Elasticsearch | 索引和存储 |
| 查询 | Kibana / Grafana | 可视化和查询 |
| 告警 | ElastAlert / Alertmanager | 异常告警 |

## 2. 日志采集

### 2.1 Filebeat 配置

```yaml
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
    fields_under_root: true
    multiline.pattern: '^\d{4}-\d{2}-\d{2}'
    multiline.negate: true
    multiline.match: after

  - type: log
    enabled: true
    paths:
      - /var/log/nginx/access.log
    fields:
      service: nginx
    fields_under_root: true

filebeat.config.modules:
  path: ${path.config}/modules.d/*.yml
  reload.enabled: false

setup.template.settings:
  index.number_of_shards: 3
  index.number_of_replicas: 1

output.kafka:
  hosts: ["kafka:9092"]
  topic: "logs"
  partition.round_robin:
    reachable_only: false
  required_acks: 1
  compression: gzip
  max_message_bytes: 1000000
```

### 2.2 Fluentd 配置

```xml
<source>
  @type tail
  path /var/log/homecare/*.log
  pos_file /var/log/td-agent/homecare.log.pos
  tag homecare.backend
  <parse>
    @type json
  </parse>
</source>

<source>
  @type forward
  port 24224
</source>

<filter homecare.**>
  @type record_transformer
  <record>
    hostname "#{Socket.gethostname}"
    environment "production"
  </record>
</filter>

<match homecare.**>
  @type kafka2
  brokers kafka:9092
  topic_key logs
  <format>
    @type json
  </format>
  <buffer>
    @type file
    path /var/log/td-agent/buffer/kafka
    flush_interval 5s
  </buffer>
</match>
```

### 2.3 应用日志规范

```python
import logging
import json
from datetime import datetime

class StructuredLogger:
    def __init__(self, name: str, service: str):
        self.logger = logging.getLogger(name)
        self.service = service

    def _format(self, level: str, message: str, **kwargs) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "service": self.service,
            "message": message,
            **kwargs,
        }
        return json.dumps(log_entry, ensure_ascii=False)

    def info(self, message: str, **kwargs):
        self.logger.info(self._format("INFO", message, **kwargs))

    def error(self, message: str, **kwargs):
        self.logger.error(self._format("ERROR", message, **kwargs))

    def warning(self, message: str, **kwargs):
        self.logger.warning(self._format("WARNING", message, **kwargs))

    def debug(self, message: str, **kwargs):
        self.logger.debug(self._format("DEBUG", message, **kwargs))
```

## 3. 日志传输

### 3.1 Kafka 主题

```yaml
# Kafka 主题配置
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaTopic
metadata:
  name: logs
spec:
  partitions: 12
  replicas: 3
  config:
    retention.ms: 86400000  # 1天
    segment.bytes: 1073741824
```

### 3.2 Logstash 处理

```ruby
input {
  kafka {
    bootstrap_servers => "kafka:9092"
    topics => ["logs"]
    group_id => "logstash"
    consumer_threads => 4
  }
}

filter {
  # 解析 JSON
  json {
    source => "message"
    target => "parsed"
  }

  # 添加时间戳
  date {
    match => ["[parsed][timestamp]", "ISO8601"]
    target => "@timestamp"
  }

  # GeoIP 解析
  if [parsed][client_ip] {
    geoip {
      source => "[parsed][client_ip]"
      target => "geoip"
    }
  }

  # 用户代理解析
  if [parsed][user_agent] {
    useragent {
      source => "[parsed][user_agent]"
      target => "user_agent"
    }
  }

  # 移除敏感字段
  mutate {
    remove_field => ["[parsed][password]", "[parsed][token]", "[parsed][authorization]"]
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "homecare-logs-%{+YYYY.MM.dd}"
    template_name => "homecare-logs"
    template => "/etc/logstash/templates/homecare.json"
    template_overwrite => true
  }
}
```

## 4. 日志存储

### 4.1 Elasticsearch 索引模板

```json
{
  "index_patterns": ["homecare-logs-*"],
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1,
    "refresh_interval": "5s",
    "index.lifecycle.name": "logs-lifecycle",
    "index.lifecycle.rollover_alias": "homecare-logs"
  },
  "mappings": {
    "properties": {
      "@timestamp": {"type": "date"},
      "level": {"type": "keyword"},
      "service": {"type": "keyword"},
      "environment": {"type": "keyword"},
      "message": {"type": "text"},
      "trace_id": {"type": "keyword"},
      "span_id": {"type": "keyword"},
      "user_id": {"type": "keyword"},
      "request_id": {"type": "keyword"},
      "duration_ms": {"type": "float"},
      "status_code": {"type": "integer"},
      "client_ip": {"type": "ip"},
      "geoip": {
        "properties": {
          "country_name": {"type": "keyword"},
          "city_name": {"type": "keyword"},
          "location": {"type": "geo_point"}
        }
      }
    }
  }
}
```

### 4.2 索引生命周期管理

```json
{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_size": "50gb",
            "max_age": "1d"
          },
          "set_priority": {"priority": 100}
        }
      },
      "warm": {
        "min_age": "3d",
        "actions": {
          "set_priority": {"priority": 50},
          "shrink": {"number_of_shards": 1},
          "forcemerge": {"max_num_segments": 1}
        }
      },
      "cold": {
        "min_age": "7d",
        "actions": {
          "set_priority": {"priority": 0},
          "freeze": {}
        }
      },
      "delete": {
        "min_age": "30d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}
```

## 5. 日志查询

### 5.1 查询 API

```python
from elasticsearch import AsyncElasticsearch

class LogQueryService:
    def __init__(self, es: AsyncElasticsearch):
        self.es = es

    async def search_logs(
        self,
        service: str = None,
        level: str = None,
        start_time: str = None,
        end_time: str = None,
        keyword: str = None,
        page: int = 1,
        size: int = 50,
    ) -> dict:
        must = []

        if service:
            must.append({"term": {"service": service}})
        if level:
            must.append({"term": {"level": level}})
        if start_time and end_time:
            must.append({
                "range": {
                    "@timestamp": {"gte": start_time, "lte": end_time}
                }
            })
        if keyword:
            must.append({"match": {"message": keyword}})

        query = {"bool": {"must": must}} if must else {"match_all": {}}

        result = await self.es.search(
            index="homecare-logs-*",
            body={
                "query": query,
                "sort": [{"@timestamp": "desc"}],
                "from": (page - 1) * size,
                "size": size,
            },
        )

        return {
            "total": result["hits"]["total"]["value"],
            "logs": [hit["_source"] for hit in result["hits"]["hits"]],
            "page": page,
            "size": size,
        }
```

### 5.2 聚合查询

```python
class LogAnalytics:
    def __init__(self, es: AsyncElasticsearch):
        self.es = es

    async def error_rate_by_service(self, start_time: str, end_time: str) -> dict:
        result = await self.es.search(
            index="homecare-logs-*",
            body={
                "query": {
                    "range": {"@timestamp": {"gte": start_time, "lte": end_time}}
                },
                "aggs": {
                    "by_service": {
                        "terms": {"field": "service"},
                        "aggs": {
                            "errors": {
                                "filter": {"term": {"level": "ERROR"}}
                            }
                        }
                    }
                },
                "size": 0,
            },
        )

        services = []
        for bucket in result["aggregations"]["by_service"]["buckets"]:
            total = bucket["doc_count"]
            errors = bucket["errors"]["doc_count"]
            services.append({
                "service": bucket["key"],
                "total": total,
                "errors": errors,
                "error_rate": errors / total if total > 0 else 0,
            })

        return {"services": services}
```

## 6. 日志分析

### 6.1 异常模式检测

```python
class LogPatternDetector:
    def __init__(self):
        self.patterns = {}

    def add_log(self, message: str):
        # 提取日志模式（替换变量部分）
        pattern = self._normalize(message)
        if pattern not in self.patterns:
            self.patterns[pattern] = 0
        self.patterns[pattern] += 1

    def _normalize(self, message: str) -> str:
        import re
        # 替换数字
        message = re.sub(r'\d+', '{N}', message)
        # 替换 UUID
        message = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '{UUID}', message)
        # 替换 IP
        message = re.sub(r'\d+\.\d+\.\d+\.\d+', '{IP}', message)
        return message

    def get_top_patterns(self, n: int = 10) -> list:
        sorted_patterns = sorted(
            self.patterns.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return [{"pattern": p, "count": c} for p, c in sorted_patterns[:n]]
```

### 6.2 日志聚类

```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import DBSCAN

class LogClusterer:
    def __init__(self):
        self.vectorizer = TfidfVectorizer(max_features=1000)
        self.clusterer = DBSCAN(eps=0.3, min_samples=5)

    def cluster(self, logs: list[str]) -> dict:
        vectors = self.vectorizer.fit_transform(logs)
        labels = self.clusterer.fit_predict(vectors)

        clusters = {}
        for log, label in zip(logs, labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(log)

        return {
            "n_clusters": len(set(labels)) - (1 if -1 in labels else 0),
            "n_noise": list(labels).count(-1),
            "clusters": {
                str(k): {"count": len(v), "examples": v[:3]}
                for k, v in clusters.items()
            },
        }
```

## 7. 日志告警

### 7.1 告警规则

```yaml
# ElastAlert 配置
name: High Error Rate Alert
type: metric_aggregation
index: homecare-logs-*
buffer_time:
  minutes: 5
metric_agg_key: level
metric_agg_type: count
query_key: service
bucket_interval:
  minutes: 1
sync_bucket_interval: true
threshold: 100
filter:
- term:
    level: ERROR
alert:
- "post"
http_post_url: "https://alertmanager/homecare/alerts"
```

### 7.2 告警规则示例

```yaml
# 错误率告警
name: Error Rate > 5%
type: spike
index: homecare-logs-*
timeframe:
  minutes: 5
spike_height: 3
spike_type: up
filter:
- term:
    level: ERROR
alert:
- "email"
email: "oncall@homecare.com"

# 特定错误关键词
name: Database Connection Error
type: any
index: homecare-logs-*
filter:
- query:
    query_string:
      query: "message: "connection refused" AND service: backend"
alert:
- "slack"
slack:
  webhook_url: "https://hooks.slack.com/..."
```

## 8. 日志平台检查清单

- [ ] 日志采集
- [ ] 日志规范
- [ ] 日志传输
- [ ] 日志存储
- [ ] 索引模板
- [ ] 生命周期管理
- [ ] 日志查询
- [ ] 聚合查询
- [ ] 异常模式检测
- [ ] 日志聚类
- [ ] 告警规则
- [ ] 可视化面板

---

*日志是系统的黑匣子。高效采集、智能分析、及时告警，让每一个问题都有迹可循。*
