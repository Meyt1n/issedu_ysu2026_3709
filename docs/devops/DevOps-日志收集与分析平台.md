# DevOps-日志收集与分析平台

> 本文档是家健镜系统日志收集与分析平台的完整设计说明，覆盖日志规范、采集架构、存储方案、检索分析、告警监控。

## 1. 概述

### 1.1 设计目标

1. 全链路日志追踪
2. 日志检索 < 3 秒
3. 支持 PB 级存储
4. 实时告警
5. 可视化分析

### 1.2 日志类型

| 类型 | 来源 | 级别 | 保留期 |
| --- | --- | --- | --- |
| 应用日志 | 后端服务 | INFO/WARN/ERROR | 30 天 |
| 访问日志 | Nginx/网关 | INFO | 30 天 |
| 错误日志 | 异常堆栈 | ERROR | 90 天 |
| 审计日志 | 关键操作 | INFO | 180 天 |
| 业务日志 | 关键业务事件 | INFO | 90 天 |
| 设备日志 | IoT 设备 | INFO | 30 天 |

## 2. 日志规范

### 2.1 日志格式

```json
{
  "timestamp": "2026-09-04T10:30:00.123Z",
  "level": "INFO",
  "service": "homecare-backend",
  "instance": "backend-7d8f9c6b5-x2k4m",
  "trace_id": "abc123def456",
  "span_id": "span789",
  "user_id": "user-uuid",
  "request_id": "req-uuid",
  "message": "用户登录成功",
  "logger": "com.homecare.auth.AuthService",
  "thread": "http-nio-8080-exec-1",
  "duration_ms": 45,
  "metadata": {
    "ip": "192.168.1.100",
    "user_agent": "Mozilla/5.0",
    "endpoint": "/api/v1/auth/login"
  }
}
```

### 2.2 日志级别

| 级别 | 使用场景 | 示例 |
| --- | --- | --- |
| ERROR | 系统错误、异常 | 数据库连接失败 |
| WARN | 潜在问题、非预期 | 接口响应超时 |
| INFO | 关键业务事件 | 用户登录、订单创建 |
| DEBUG | 调试信息 | 方法入参出参 |
| TRACE | 详细追踪 | 完整调用链 |

### 2.3 日志配置

```python
import logging
import json
from datetime import datetime

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            'timestamp': datetime.utcfromtimestamp(record.created).isoformat() + 'Z',
            'level': record.levelname,
            'service': 'homecare-backend',
            'message': record.getMessage(),
            'logger': record.name,
            'thread': record.threadName,
        }

        if hasattr(record, 'trace_id'):
            log_entry['trace_id'] = record.trace_id
        if hasattr(record, 'user_id'):
            log_entry['user_id'] = record.user_id
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/var/log/homecare/app.log'),
    ],
)

# 设置 JSON 格式
for handler in logging.getLogger().handlers:
    handler.setFormatter(JsonFormatter())
```

## 3. 采集架构

### 3.1 ELK 架构

```
应用服务
    ↓ (Filebeat)
Kafka (缓冲)
    ↓
Logstash (处理)
    ↓
Elasticsearch (存储)
    ↓
Kibana (可视化)
```

### 3.2 Filebeat 配置

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
      environment: prod

  - type: log
    enabled: true
    paths:
      - /var/log/nginx/access.log
    fields:
      service: nginx
      log_type: access

output.kafka:
  hosts: ["kafka:9092"]
  topic: "logs-%{[fields.service]}"
  partition.round_robin:
    reachable_only: false
  required_acks: 1
  compression: gzip
```

### 3.3 Logstash 配置

```ruby
input {
  kafka {
    bootstrap_servers => "kafka:9092"
    topics_pattern => "logs-.*"
    group_id => "logstash"
    codec => json
  }
}

filter {
  # 解析时间
  date {
    match => ["timestamp", "ISO8601"]
    target => "@timestamp"
  }

  # 添加环境信息
  mutate {
    add_field => {
      "environment" => "prod"
      "cluster" => "homecare-prod"
    }
  }

  # 脱敏处理
  mutate {
    gsub => [
      "message", "1[3-9]\d{9}", "1**********",
      "message", "\d{17}[\dXx]", "******************"
    ]
  }

  # 丢弃 DEBUG 日志（生产环境）
  if [level] == "DEBUG" {
    drop {}
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "homecare-logs-%{+YYYY.MM.dd}"
    template_name => "homecare-logs"
    template_overwrite => true
  }
}
```

## 4. 存储方案

### 4.1 Elasticsearch 索引

```json
{
  "mappings": {
    "properties": {
      "@timestamp": {"type": "date"},
      "level": {"type": "keyword"},
      "service": {"type": "keyword"},
      "instance": {"type": "keyword"},
      "trace_id": {"type": "keyword"},
      "user_id": {"type": "keyword"},
      "request_id": {"type": "keyword"},
      "message": {"type": "text", "analyzer": "ik_max_word"},
      "logger": {"type": "keyword"},
      "duration_ms": {"type": "integer"},
      "metadata": {
        "properties": {
          "ip": {"type": "ip"},
          "endpoint": {"type": "keyword"}
        }
      }
    }
  },
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1,
    "index.lifecycle.name": "logs-lifecycle",
    "index.lifecycle.rollover_alias": "homecare-logs"
  }
}
```

### 4.2 索引生命周期

```json
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_size": "50gb",
            "max_age": "1d"
          }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "shrink": {"number_of_shards": 1},
          "forcemerge": {"max_num_segments": 1}
        }
      },
      "cold": {
        "min_age": "30d",
        "actions": {
          "freeze": {}
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}
```

## 5. 检索分析

### 5.1 常用查询

```python
from elasticsearch import AsyncElasticsearch

class LogSearchService:
    def __init__(self, es_host: str):
        self.es = AsyncElasticsearch(hosts=[es_host])

    async def search_logs(
        self,
        keyword: str = None,
        level: str = None,
        service: str = None,
        trace_id: str = None,
        start_time: str = None,
        end_time: str = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        query = {"bool": {"must": [], "filter": []}}

        if keyword:
            query["bool"]["must"].append({
                "match": {"message": keyword}
            })

        if level:
            query["bool"]["filter"].append({"term": {"level": level}})
        if service:
            query["bool"]["filter"].append({"term": {"service": service}})
        if trace_id:
            query["bool"]["filter"].append({"term": {"trace_id": trace_id}})

        if start_time or end_time:
            range_query = {"@timestamp": {}}
            if start_time:
                range_query["@timestamp"]["gte"] = start_time
            if end_time:
                range_query["@timestamp"]["lte"] = end_time
            query["bool"]["filter"].append({"range": range_query})

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

    async def get_trace_logs(self, trace_id: str) -> list[dict]:
        result = await self.es.search(
            index="homecare-logs-*",
            body={
                "query": {"term": {"trace_id": trace_id}},
                "sort": [{"@timestamp": "asc"}],
                "size": 100,
            },
        )
        return [hit["_source"] for hit in result["hits"]["hits"]]
```

### 5.2 聚合分析

```python
class LogAnalyticsService:
    async def error_rate_by_service(self, start_time: str, end_time: str) -> dict:
        result = await self.es.search(
            index="homecare-logs-*",
            body={
                "size": 0,
                "query": {
                    "range": {"@timestamp": {"gte": start_time, "lte": end_time}}
                },
                "aggs": {
                    "by_service": {
                        "terms": {"field": "service"},
                        "aggs": {
                            "by_level": {
                                "terms": {"field": "level"}
                            }
                        }
                    }
                },
            },
        )
        return result["aggregations"]

    async def slow_requests(self, threshold_ms: int = 1000, size: int = 20) -> list[dict]:
        result = await self.es.search(
            index="homecare-logs-*",
            body={
                "query": {
                    "range": {"duration_ms": {"gte": threshold_ms}}
                },
                "sort": [{"duration_ms": "desc"}],
                "size": size,
            },
        )
        return [hit["_source"] for hit in result["hits"]["hits"]]
```

## 6. 告警监控

### 6.1 告警规则

```python
class AlertManager:
    def __init__(self, es_client, notification_service):
        self.es = es_client
        self.notification = notification_service

    async def check_error_spike(self, service: str, threshold: int = 10):
        # 检查最近 5 分钟错误数
        result = await self.es.count(
            index="homecare-logs-*",
            body={
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"level": "ERROR"}},
                            {"term": {"service": service}},
                            {"range": {"@timestamp": {"gte": "now-5m"}}}
                        ]
                    }
                }
            },
        )

        count = result["count"]
        if count > threshold:
            await self.notification.send_alert(
                title=f"{service} 错误数激增",
                message=f"最近 5 分钟错误数: {count}, 阈值: {threshold}",
                level="critical",
            )

    async def check_slow_endpoints(self, threshold_p99: int = 2000):
        # 检查 P99 响应时间
        result = await self.es.search(
            index="homecare-logs-*",
            body={
                "size": 0,
                "query": {
                    "range": {"@timestamp": {"gte": "now-5m"}}
                },
                "aggs": {
                    "by_endpoint": {
                        "terms": {"field": "metadata.endpoint"},
                        "aggs": {
                            "p99_duration": {
                                "percentiles": {
                                    "field": "duration_ms",
                                    "percents": [99]
                                }
                            }
                        }
                    }
                },
            },
        )
        # 检查超过阈值的端点
        pass
```

### 6.2 告警通道

| 通道 | 用途 | 级别 |
| --- | --- | --- |
| 邮件 | 常规告警 | WARN+ |
| 短信 | 紧急告警 | CRITICAL |
| 钉钉/企业微信 | 团队通知 | ERROR+ |
| 电话 | 重大故障 | CRITICAL |

## 7. 日志平台检查清单

- [ ] 日志格式
- [ ] 日志级别
- [ ] 日志配置
- [ ] Filebeat 采集
- [ ] Kafka 缓冲
- [ ] Logstash 处理
- [ ] Elasticsearch 存储
- [ ] 索引生命周期
- [ ] 日志检索
- [ ] 聚合分析
- [ ] 告警规则
- [ ] 告警通道

---

*完善的日志平台是运维的眼睛。全链路追踪、实时检索、智能告警，让问题无处遁形。*
