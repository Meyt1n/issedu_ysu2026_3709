# DevOps-成本优化与资源管理

> 本文档是家健镜系统成本优化与资源管理的完整指南，覆盖计算优化、存储优化、网络优化、自动扩缩容、成本监控。

## 1. 概述

### 1.1 优化目标

1. 降低 30% 云成本
2. 资源利用率 > 60%
3. 不影响性能和可用性
4. 成本可观测
5. 持续优化

### 1.2 成本构成

| 类别 | 占比 | 优化重点 |
| --- | --- | --- |
| 计算 | 40% | 实例规格、自动扩缩容 |
| 存储 | 25% | 存储分层、生命周期 |
| 网络 | 15% | 流量优化、CDN |
| 数据库 | 15% | 实例规格、读写分离 |
| 其他 | 5% | 监控、日志等 |

## 2. 计算优化

### 2.1 实例规格选择

```python
class InstanceOptimizer:
    def recommend_instance(self, cpu_usage, memory_usage, traffic):
        # 基于实际使用推荐规格
        if cpu_usage < 20 and memory_usage < 40:
            return "降配：当前资源利用率过低"
        elif cpu_usage > 80 or memory_usage > 80:
            return "升配：资源即将成为瓶颈"
        else:
            return "规格合适"

    def calculate_cost_savings(self, current, recommended):
        current_cost = self._get_instance_cost(current)
        recommended_cost = self._get_instance_cost(recommended)
        return {
            "current_cost": current_cost,
            "recommended_cost": recommended_cost,
            "savings": current_cost - recommended_cost,
            "savings_percent": (current_cost - recommended_cost) / current_cost * 100,
        }
```

### 2.2 预留实例

```python
class ReservedInstancePlanner:
    def __init__(self, usage_history):
        self.usage_history = usage_history

    def analyze(self):
        # 分析实例使用情况
        steady_instances = self._find_steady_instances()
        variable_instances = self._find_variable_instances()

        return {
            "steady_instances": steady_instances,  # 适合预留实例
            "variable_instances": variable_instances,  # 适合按需/竞价
            "recommendation": self._generate_recommendation(),
        }

    def _find_steady_instances(self):
        # 运行时间 > 70% 的实例
        return [
            instance for instance in self.usage_history
            if instance['utilization'] > 0.7
        ]

    def calculate_savings(self, instance_type, term: int = 1):
        on_demand_cost = self._get_on_demand_cost(instance_type)
        reserved_cost = self._get_reserved_cost(instance_type, term)
        return on_demand_cost - reserved_cost
```

### 2.3 竞价实例

```yaml
# Kubernetes 中使用竞价实例
apiVersion: apps/v1
kind: Deployment
metadata:
  name: batch-processor
spec:
  replicas: 3
  template:
    spec:
      nodeSelector:
        node-type: spot  # 竞价实例节点
      tolerations:
        - key: "spot"
          operator: "Equal"
          value: "true"
          effect: "NoSchedule"
      containers:
        - name: processor
          image: homecare/batch-processor
```

## 3. 存储优化

### 3.1 存储分层

```python
class StorageTierManager:
    def __init__(self):
        self.tiers = {
            "hot": {"cost": 0.023, "access": "frequent"},
            "warm": {"cost": 0.0125, "access": "infrequent"},
            "cold": {"cost": 0.004, "access": "rare"},
            "archive": {"cost": 0.00099, "access": "archived"},
        }

    def recommend_tier(self, file):
        age_days = (datetime.now() - file['last_accessed']).days
        access_count = file['access_count_30d']

        if age_days < 7 and access_count > 10:
            return "hot"
        elif age_days < 30:
            return "warm"
        elif age_days < 90:
            return "cold"
        else:
            return "archive"

    def estimate_savings(self, files):
        total_current_cost = sum(f['size'] * self.tiers['hot']['cost'] for f in files)
        total_optimized_cost = sum(
            f['size'] * self.tiers[self.recommend_tier(f)]['cost']
            for f in files
        )
        return total_current_cost - total_optimized_cost
```

### 3.2 生命周期策略

```json
{
  "rules": [
    {
      "id": "move-to-warm-after-30-days",
      "status": "enabled",
      "prefix": "uploads/",
      "transitions": [
        {
          "days": 30,
          "storage_class": "STANDARD_IA"
        },
        {
          "days": 90,
          "storage_class": "GLACIER"
        }
      ],
      "expiration": {
        "days": 365
      }
    }
  ]
}
```

### 3.3 日志存储优化

```yaml
# Loki 日志存储分层
schema_config:
  configs:
    - from: 2024-01-01
      store: boltdb-shipper
      object_store: s3
      schema: v11
      index:
        prefix: index_
        period: 24h

storage_config:
  aws:
    s3: s3://homecare-logs
    s3forcepathstyle: true

limits_config:
  retention_period: 168h  # 7天热存储
  split_queries_by_interval: 24h

compactor:
  working_directory: /data/loki/compactor
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150
```

## 4. 网络优化

### 4.1 CDN 加速

```python
class CDNOptimizer:
    def __init__(self):
        self.cacheable_extensions = {
            '.jpg', '.jpeg', '.png', '.gif', '.webp',
            '.css', '.js', '.woff', '.woff2', '.ttf',
            '.pdf', '.mp4', '.webm',
        }

    def should_cache(self, url):
        return any(url.endswith(ext) for ext in self.cacheable_extensions)

    def configure_cache_headers(self, url):
        if self.should_cache(url):
            return {
                "Cache-Control": "public, max-age=31536000, immutable",
                "CDN-Cache-Control": "max-age=31536000",
            }
        return {
            "Cache-Control": "no-cache",
        }
```

### 4.2 流量优化

```python
class TrafficOptimizer:
    def compress_response(self, response):
        # Gzip/Brotli 压缩
        if 'text' in response.content_type or 'json' in response.content_type:
            return brotli.compress(response.content)
        return response.content

    def optimize_images(self, image_path, quality=80):
        # 图片压缩和格式转换
        image = Image.open(image_path)
        optimized_path = image_path.replace('.png', '.webp')
        image.save(optimized_path, 'WEBP', quality=quality)
        return optimized_path
```

## 5. 自动扩缩容

### 5.1 HPA 配置

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: backend-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: homecare-backend
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 30
```

### 5.2 定时扩缩容

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: backend-scheduled-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: homecare-backend
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: External
      external:
        metric:
          name: scheduled_replicas
        target:
          type: AverageValue
          averageValue: "5"
```

### 5.3 VPA 配置

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: backend-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: homecare-backend
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
      - containerName: '*'
        minAllowed:
          cpu: 100m
          memory: 128Mi
        maxAllowed:
          cpu: 2
          memory: 2Gi
```

## 6. 成本监控

### 6.1 成本标签

```yaml
# 所有资源都打成本标签
apiVersion: apps/v1
kind: Deployment
metadata:
  labels:
    cost-center: healthcare
    environment: production
    team: backend
    project: homecare
spec:
  template:
    metadata:
      labels:
        cost-center: healthcare
        environment: production
```

### 6.2 成本报表

```python
class CostReporter:
    def generate_monthly_report(self, month):
        report = {
            "month": month,
            "total_cost": self._get_total_cost(month),
            "by_service": self._get_cost_by_service(month),
            "by_team": self._get_cost_by_team(month),
            "trend": self._get_cost_trend(month),
            "savings": self._get_savings(month),
        }
        return report

    def _get_cost_by_service(self, month):
        return {
            "compute": 12000,
            "storage": 5000,
            "network": 3000,
            "database": 4500,
            "other": 1500,
        }
```

### 6.3 预算告警

```python
class BudgetAlert:
    def __init__(self, budget: float):
        self.budget = budget
        self.thresholds = [0.5, 0.8, 0.9, 1.0]

    def check(self, current_spend: float):
        alerts = []
        for threshold in self.thresholds:
            if current_spend >= self.budget * threshold:
                alerts.append({
                    "threshold": threshold,
                    "message": f"已使用预算的 {threshold*100:.0f}%",
                    "severity": "warning" if threshold < 1.0 else "critical",
                })
        return alerts
```

## 7. FinOps 实践

### 7.1 成本分配

```python
class CostAllocation:
    def allocate(self, total_cost, usage):
        allocated = {}
        total_usage = sum(usage.values())

        for team, team_usage in usage.items():
            allocated[team] = total_cost * (team_usage / total_usage)

        return allocated
```

### 7.2 优化建议

```python
class OptimizationAdvisor:
    def analyze(self, resources):
        recommendations = []

        for resource in resources:
            if resource['cpu_utilization'] < 20:
                recommendations.append({
                    "resource": resource['name'],
                    "type": "rightsizing",
                    "suggestion": "降配 CPU",
                    "estimated_savings": resource['cost'] * 0.3,
                })

            if resource['storage_growth'] > 0.5:
                recommendations.append({
                    "resource": resource['name'],
                    "type": "storage",
                    "suggestion": "启用生命周期管理",
                    "estimated_savings": resource['storage_cost'] * 0.4,
                })

        return sorted(recommendations, key=lambda x: x['estimated_savings'], reverse=True)
```

## 8. 成本优化检查清单

- [ ] 实例规格优化
- [ ] 预留实例
- [ ] 竞价实例
- [ ] 存储分层
- [ ] 生命周期策略
- [ ] 日志存储优化
- [ ] CDN 加速
- [ ] 流量压缩
- [ ] HPA 配置
- [ ] VPA 配置
- [ ] 成本标签
- [ ] 预算告警

---

*成本优化是持续的过程。精准的监控、智能的调度、合理的分层，让每一分钱都花在刀刃上。*
