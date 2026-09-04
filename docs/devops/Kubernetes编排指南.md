# Kubernetes编排指南

> 本文档是家健镜系统 Kubernetes 编排的完整指南，覆盖集群架构、工作负载、服务发现、配置管理、存储、自动扩缩容。面向运维人员和后端开发者，作为 K8s 部署的权威依据。

## 1. K8s 概述

### 1.1 设计目标

1. **高可用**：多副本、自动恢复
2. **弹性伸缩**：根据负载自动扩缩容
3. **滚动更新**：零停机发布
4. **服务发现**：动态服务注册和发现
5. **资源隔离**：命名空间和资源配额

### 1.2 集群架构

```
                    ┌─────────────────┐
                    │   Ingress       │ ← 入口、TLS、路由
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   Service       │ ← 负载均衡
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
    ┌─────▼─────┐     ┌─────▼─────┐     ┌─────▼─────┐
    │   Pod     │     │   Pod     │     │   Pod     │ ← 应用实例
    │ (backend) │     │ (backend) │     │ (backend) │
    └───────────┘     └───────────┘     └───────────┘
```

## 2. 工作负载

### 2.1 Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: homecare-backend
  namespace: homecare
  labels:
    app: backend
    version: v1.2.3
spec:
  replicas: 3
  selector:
    matchLabels:
      app: backend
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: backend
        version: v1.2.3
    spec:
      serviceAccountName: homecare-backend
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
        - name: backend
          image: homecare/backend:v1.2.3
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8000
              name: http
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: homecare-secrets
                  key: database-url
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: homecare-secrets
                  key: redis-url
            - name: LOG_LEVEL
              valueFrom:
                configMapKeyRef:
                  name: homecare-config
                  key: log-level
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2"
              memory: "2Gi"
          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /health/detailed
              port: http
            initialDelaySeconds: 10
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
          startupProbe:
            httpGet:
              path: /health
              port: http
            failureThreshold: 30
            periodSeconds: 10
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
```

### 2.2 StatefulSet（数据库）

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: homecare
spec:
  serviceName: postgres
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
        - name: postgres
          image: postgres:15-alpine
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRES_DB
              value: homecare
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: postgres-secret
                  key: username
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-secret
                  key: password
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
          resources:
            requests:
              cpu: "1"
              memory: "1Gi"
            limits:
              cpu: "4"
              memory: "4Gi"
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 50Gi
```

## 3. 服务与网络

### 3.1 Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: backend
  namespace: homecare
spec:
  selector:
    app: backend
  ports:
    - port: 80
      targetPort: http
      name: http
  type: ClusterIP
```

### 3.2 Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: homecare-ingress
  namespace: homecare
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
spec:
  tls:
    - hosts:
        - api.homecare.example.com
      secretName: homecare-tls
  rules:
    - host: api.homecare.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: backend
                port:
                  number: 80
```

## 4. 配置管理

### 4.1 ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: homecare-config
  namespace: homecare
data:
  log-level: "INFO"
  max-upload-size: "52428800"
  session-timeout: "1800"
  default-language: "zh-CN"
```

### 4.2 Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: homecare-secrets
  namespace: homecare
type: Opaque
stringData:
  database-url: "postgresql://user:pass@postgres:5432/homecare"
  redis-url: "redis://redis:6379/0"
  jwt-secret: "your-super-secret-key"
```

## 5. 自动扩缩容

### 5.1 HPA

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: backend-hpa
  namespace: homecare
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: homecare-backend
  minReplicas: 3
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
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 25
          periodSeconds: 120
```

## 6. 常用命令

```bash
# 查看资源
kubectl get pods -n homecare
kubectl get deployments -n homecare
kubectl get services -n homecare

# 查看日志
kubectl logs -f deployment/homecare-backend -n homecare

# 进入容器
kubectl exec -it deployment/homecare-backend -n homecare -- bash

# 滚动更新
kubectl set image deployment/homecare-backend backend=homecare/backend:v1.2.4 -n homecare

# 查看更新状态
kubectl rollout status deployment/homecare-backend -n homecare

# 回滚
kubectl rollout undo deployment/homecare-backend -n homecare

# 扩缩容
kubectl scale deployment/homecare-backend --replicas=5 -n homecare

# 查看事件
kubectl get events -n homecare --sort-by='.lastTimestamp'
```

## 7. K8s检查清单

- [ ] Deployment 配置
- [ ] 健康检查（liveness/readiness）
- [ ] 资源限制（requests/limits）
- [ ] 非 root 用户
- [ ] ConfigMap 配置
- [ ] Secret 密钥管理
- [ ] Service 服务发现
- [ ] Ingress 路由
- [ ] HPA 自动扩缩容
- [ ] 滚动更新策略
- [ ] 持久化存储
- [ ] 命名空间隔离
- [ ] 资源配额
- [ ] 网络策略

---

*Kubernetes 是云原生的操作系统。弹性、可靠、自动化的编排，让系统轻松应对任何负载。*
