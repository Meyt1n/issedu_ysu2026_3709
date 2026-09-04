# DevOps-安全扫描与漏洞管理

> 本文档是家健镜系统安全扫描与漏洞管理的完整设计说明，覆盖代码扫描、依赖扫描、镜像扫描、运行时安全、漏洞修复流程。

## 1. 概述

### 1.1 设计目标

1. 漏洞发现率 > 95%
2. 高危漏洞 24 小时内修复
3. 扫描自动化
4. 全链路覆盖
5. 合规可审计

### 1.2 安全扫描层级

| 层级 | 扫描内容 | 工具 |
| --- | --- | --- |
| 代码层 | 代码漏洞、编码规范 | SonarQube、CodeQL |
| 依赖层 | 第三方库漏洞 | Snyk、Dependabot |
| 镜像层 | 容器镜像漏洞 | Trivy、Clair |
| 运行层 | 运行时威胁 | Falco、Sysdig |
| 基础设施 | 配置安全 | Checkov、tfsec |

## 2. 代码安全扫描

### 2.1 SonarQube 集成

```yaml
# .github/workflows/sonarqube.yml
name: SonarQube Scan
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

jobs:
  sonarqube:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0

      - name: SonarQube Scan
        uses: SonarSource/sonarqube-scan-action@master
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
          SONAR_HOST_URL: ${{ secrets.SONAR_HOST_URL }}
```

### 2.2 CodeQL 分析

```yaml
name: CodeQL Analysis
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]
  schedule:
    - cron: '0 0 * * 0'

jobs:
  analyze:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        language: ['python', 'javascript']
    steps:
      - uses: actions/checkout@v3

      - name: Initialize CodeQL
        uses: github/codeql-action/init@v2
        with:
          languages: ${{ matrix.language }}

      - name: Autobuild
        uses: github/codeql-action/autobuild@v2

      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v2
```

### 2.3 代码规范检查

```python
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files

  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black
        language_version: python3.10

  - repo: https://github.com/PyCQA/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
        args: [--max-line-length=120]

  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.5
    hooks:
      - id: bandit
        args: [-r, -ll, -ii]
```

## 3. 依赖安全扫描

### 3.1 Snyk 扫描

```yaml
name: Snyk Security
on:
  push:
    branches: [master]
  pull_request:

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Run Snyk to check for vulnerabilities
        uses: snyk/actions/python@master
        env:
          SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
        with:
          args: --severity-threshold=high

      - name: Snyk Code Analysis
        uses: snyk/actions/node@master
        env:
          SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
        with:
          command: code test
```

### 3.2 Dependabot

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "daily"
    open-pull-requests-limit: 10
    labels:
      - "dependencies"
      - "security"

  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"

  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

### 3.3 依赖更新策略

```python
class DependencyManager:
    def __init__(self):
        self.vulnerability_db = {}

    def check_vulnerabilities(self, dependencies: dict) -> list[dict]:
        vulnerabilities = []
        for package, version in dependencies.items():
            if package in self.vulnerability_db:
                vulns = self.vulnerability_db[package]
                for vuln in vulns:
                    if self._is_vulnerable(version, vuln['affected_versions']):
                        vulnerabilities.append({
                            'package': package,
                            'version': version,
                            'vulnerability': vuln,
                            'severity': vuln['severity'],
                            'fixed_version': vuln.get('fixed_version'),
                        })
        return vulnerabilities

    def _is_vulnerable(self, version: str, affected: list[str]) -> bool:
        # 版本比较逻辑
        pass
```

## 4. 容器镜像扫描

### 4.1 Trivy 扫描

```yaml
name: Container Scan
on:
  push:
    branches: [master]
  pull_request:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build Docker image
        run: docker build -t homecare-backend:${{ github.sha }} .

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: homecare-backend:${{ github.sha }}
          format: 'sarif'
          output: 'trivy-results.sarif'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'

      - name: Upload Trivy scan results
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: 'trivy-results.sarif'
```

### 4.2 安全基础镜像

```dockerfile
# 多阶段构建，最小化攻击面
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.11-slim

# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app
COPY --from=builder /root/.local /home/appuser/.local
COPY --chown=appuser:appuser . .

# 安全加固
RUN apt-get update && apt-get install -y --no-install-recommends     curl     && rm -rf /var/lib/apt/lists/*

USER appuser
ENV PATH="/home/appuser/.local/bin:${PATH}"

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 4.3 镜像签名

```bash
# 镜像签名
cosign sign --key cosign.key homecare-backend:v1.0.0

# 验证签名
cosign verify --key cosign.pub homecare-backend:v1.0.0
```

## 5. 运行时安全

### 5.1 Falco 规则

```yaml
# falco_rules.yaml
- rule: Shell Run in Container
  desc: A shell was run inside a container
  condition: container.id != host and proc.name in (bash, sh, zsh)
  output: "Shell run in container (user=%user.name container=%container.name)"
  priority: WARNING

- rule: Sensitive File Read
  desc: Read of sensitive file
  condition: open_read and fd.name in (/etc/shadow, /etc/passwd)
  output: "Sensitive file read (file=%fd.name user=%user.name)"
  priority: CRITICAL

- rule: Unexpected Network Connection
  desc: Container made unexpected outbound connection
  condition: outbound and container.id != host and not fd.sip in (allowed_ips)
  output: "Unexpected network connection (ip=%fd.sip port=%fd.sport)"
  priority: WARNING
```

### 5.2 网络策略

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-network-policy
spec:
  podSelector:
    matchLabels:
      app: homecare-backend
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: api-gateway
      ports:
        - protocol: TCP
          port: 8000
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: mysql
      ports:
        - protocol: TCP
          port: 3306
    - to:
        - podSelector:
            matchLabels:
              app: redis
      ports:
        - protocol: TCP
          port: 6379
```

## 6. 漏洞管理流程

### 6.1 漏洞分级

| 级别 | CVSS | 修复时限 | 处理要求 |
| --- | --- | --- | --- |
| 严重 Critical | 9.0-10.0 | 24 小时 | 立即修复，紧急发布 |
| 高危 High | 7.0-8.9 | 7 天 | 优先修复，计划发布 |
| 中危 Medium | 4.0-6.9 | 30 天 | 排期修复 |
| 低危 Low | 0.1-3.9 | 90 天 | 择机修复 |

### 6.2 漏洞跟踪

```python
class VulnerabilityManager:
    def __init__(self, db):
        self.db = db

    async def report_vulnerability(self, vuln: dict):
        await self.db.execute(
            '''INSERT INTO vulnerabilities
               (id, title, severity, cvss, package, affected_version,
                fixed_version, description, status, discovered_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'open', NOW())''',
            vuln['id'], vuln['title'], vuln['severity'],
            vuln['cvss'], vuln['package'], vuln['affected_version'],
            vuln.get('fixed_version'), vuln['description'],
        )

    async def get_vulnerabilities(self, severity: str = None) -> list:
        query = "SELECT * FROM vulnerabilities WHERE 1=1"
        params = []
        if severity:
            query += " AND severity = $1"
            params.append(severity)
        return await self.db.fetch(query, *params)

    async def fix_vulnerability(self, vuln_id: str, fixed_by: str):
        await self.db.execute(
            '''UPDATE vulnerabilities
               SET status = 'fixed', fixed_by = $1, fixed_at = NOW()
               WHERE id = $2''',
            fixed_by, vuln_id,
        )
```

### 6.3 修复验证

```python
class FixVerifier:
    def verify_fix(self, vuln: dict, new_version: str) -> bool:
        # 1. 确认新版本不包含漏洞
        if self._is_vulnerable(new_version, vuln['affected_versions']):
            return False

        # 2. 运行回归测试
        test_result = self._run_regression_tests()
        if not test_result.passed:
            return False

        # 3. 重新扫描确认
        scan_result = self._rescan()
        return vuln['id'] not in scan_result
```

## 7. 安全合规

### 7.1 合规检查清单

```markdown
## 安全合规检查清单

### 数据保护
- [ ] 敏感数据加密存储
- [ ] 传输加密（TLS 1.3）
- [ ] 数据脱敏
- [ ] 数据备份加密
- [ ] 数据访问审计

### 访问控制
- [ ] 最小权限原则
- [ ] 多因素认证
- [ ] 会话管理
- [ ] 权限定期审查
- [ ] 账号生命周期管理

### 代码安全
- [ ] 代码审查
- [ ] 安全扫描
- [ ] 依赖管理
- [ ] 密钥管理
- [ ] 日志审计

### 基础设施
- [ ] 网络隔离
- [ ] 防火墙规则
- [ ] 容器安全
- [ ] 主机加固
- [ ] 监控告警
```

## 8. 安全扫描检查清单

- [ ] 代码扫描
- [ ] CodeQL 分析
- [ ] 代码规范
- [ ] 依赖扫描
- [ ] Dependabot
- [ ] 镜像扫描
- [ ] 安全基础镜像
- [ ] 镜像签名
- [ ] 运行时安全
- [ ] 网络策略
- [ ] 漏洞管理
- [ ] 安全合规

---

*安全是系统的生命线。全链路扫描、自动化检测、快速修复，让安全左移、风险可控。*
