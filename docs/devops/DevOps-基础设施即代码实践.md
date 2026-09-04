# DevOps-基础设施即代码实践

> 本文档是家健镜系统基础设施即代码（IaC）的完整实践指南，覆盖 Terraform、Ansible、环境管理、状态管理。

## 1. 概述

### 1.1 IaC 目标

1. 可复现：环境可一键重建
2. 可版本化：基础设施变更有历史
3. 可审查：变更通过 PR 审核
4. 自动化：减少人工操作
5. 一致性：多环境配置一致

### 1.2 工具选型

| 工具 | 用途 | 优势 |
| --- | --- | --- |
| Terraform | 云资源编排 | 多云支持、状态管理 |
| Ansible | 配置管理 | 无 Agent、YAML 语法 |
| Docker | 容器化 | 环境一致性 |
| Kubernetes | 容器编排 | 自动扩缩容 |

## 2. Terraform 实践

### 2.1 目录结构

```
infrastructure/
├── terraform/
│   ├── modules/
│   │   ├── vpc/
│   │   ├── database/
│   │   ├── kubernetes/
│   │   └── monitoring/
│   ├── environments/
│   │   ├── dev/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── terraform.tfvars
│   │   ├── staging/
│   │   └── production/
│   └── backend.tf
```

### 2.2 模块定义

```hcl
# modules/database/main.tf
variable "engine" {
  type    = string
  default = "postgres"
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "allocated_storage" {
  type    = number
  default = 20
}

variable "environment" {
  type = string
}

resource "aws_db_instance" "main" {
  engine               = var.engine
  instance_class       = var.instance_class
  allocated_storage    = var.allocated_storage
  db_name              = "homecare_${var.environment}"
  username             = "admin"
  password             = var.db_password
  skip_final_snapshot  = true
  tags = {
    Environment = var.environment
    Project     = "homecare"
  }
}

output "endpoint" {
  value = aws_db_instance.main.endpoint
}

output "port" {
  value = aws_db_instance.main.port
}
```

### 2.3 环境配置

```hcl
# environments/dev/main.tf
terraform {
  backend "s3" {
    bucket = "homecare-terraform-state"
    key    = "dev/terraform.tfstate"
    region = "cn-north-1"
  }
}

provider "aws" {
  region = "cn-north-1"
}

module "vpc" {
  source = "../../modules/vpc"
  environment = "dev"
  cidr = "10.0.0.0/16"
}

module "database" {
  source = "../../modules/database"
  environment = "dev"
  instance_class = "db.t3.micro"
  allocated_storage = 20
  db_password = var.db_password
}

module "kubernetes" {
  source = "../../modules/kubernetes"
  environment = "dev"
  node_count = 2
  instance_type = "t3.small"
}
```

### 2.4 变量定义

```hcl
# environments/dev/variables.tf
variable "db_password" {
  type      = string
  sensitive = true
}

variable "region" {
  type    = string
  default = "cn-north-1"
}
```

### 2.5 状态管理

```hcl
# backend.tf
terraform {
  backend "s3" {
    bucket         = "homecare-terraform-state"
    key            = "production/terraform.tfstate"
    region         = "cn-north-1"
    encrypt        = true
    dynamodb_table = "terraform-locks"
  }
}
```

## 3. Ansible 实践

### 3.1 目录结构

```
ansible/
├── inventory/
│   ├── dev/
│   │   ├── hosts.ini
│   │   └── group_vars/
│   ├── staging/
│   └── production/
├── roles/
│   ├── common/
│   ├── docker/
│   ├── database/
│   ├── monitoring/
│   └── application/
├── playbooks/
│   ├── setup.yml
│   ├── deploy.yml
│   └── backup.yml
└── ansible.cfg
```

### 3.2 Inventory

```ini
# inventory/dev/hosts.ini
[webservers]
web-01 ansible_host=10.0.1.10
web-02 ansible_host=10.0.1.11

[databases]
db-01 ansible_host=10.0.2.10

[monitoring]
monitor-01 ansible_host=10.0.3.10

[homecare:children]
webservers
databases
```

### 3.3 Role 定义

```yaml
# roles/common/tasks/main.yml
- name: 更新系统包
  apt:
    upgrade: dist
    update_cache: yes

- name: 安装基础工具
  apt:
    name:
      - curl
      - wget
      - vim
      - htop
      - git
    state: present

- name: 设置时区
  timezone:
    name: Asia/Shanghai

- name: 配置 NTP
  apt:
    name: chrony
    state: present
  notify: restart chrony
```

### 3.4 Playbook

```yaml
# playbooks/setup.yml
- name: 配置所有服务器
  hosts: all
  become: yes
  roles:
    - common

- name: 配置 Web 服务器
  hosts: webservers
  become: yes
  roles:
    - docker
    - application

- name: 配置数据库服务器
  hosts: databases
  become: yes
  roles:
    - database

- name: 配置监控服务器
  hosts: monitoring
  become: yes
  roles:
    - monitoring
```

## 4. CI/CD 集成

### 4.1 Terraform CI

```yaml
# .github/workflows/terraform.yml
name: Terraform

on:
  pull_request:
    paths:
      - "infrastructure/terraform/**"

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v2
        with:
          terraform_version: 1.5.0

      - name: Terraform Init
        run: terraform init
        working-directory: infrastructure/terraform/environments/dev

      - name: Terraform Format
        run: terraform fmt -check
        working-directory: infrastructure/terraform/environments/dev

      - name: Terraform Validate
        run: terraform validate
        working-directory: infrastructure/terraform/environments/dev

      - name: Terraform Plan
        run: terraform plan -out=tfplan
        working-directory: infrastructure/terraform/environments/dev
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

### 4.2 自动应用

```yaml
  apply:
    needs: validate
    if: github.ref == 'refs/heads/master'
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v3
      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v2
      - name: Terraform Init
        run: terraform init
        working-directory: infrastructure/terraform/environments/production
      - name: Terraform Apply
        run: terraform apply -auto-approve
        working-directory: infrastructure/terraform/environments/production
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

## 5. 环境管理

### 5.1 环境隔离

| 环境 | 用途 | 数据 | 规模 |
| --- | --- | --- | --- |
| dev | 开发测试 | 模拟数据 | 最小 |
| staging | 预发布 | 生产快照 | 中等 |
| production | 生产 | 真实数据 | 完整 |

### 5.2 配置差异

```hcl
# dev 环境
instance_class = "db.t3.micro"
node_count = 2
allocated_storage = 20

# production 环境
instance_class = "db.r5.large"
node_count = 5
allocated_storage = 100
multi_az = true
backup_retention = 7
```

## 6. 最佳实践

### 6.1 命名规范

```
资源命名：{project}-{environment}-{resource_type}-{index}
示例：homecare-dev-web-01
      homecare-prod-db-01
```

### 6.2 标签规范

```hcl
tags = {
  Project     = "homecare"
  Environment = var.environment
  ManagedBy   = "terraform"
  Owner       = "devops-team"
  CostCenter  = "healthcare"
}
```

### 6.3 敏感信息管理

```hcl
# 使用 AWS Secrets Manager
data "aws_secretsmanager_secret_version" "db_password" {
  secret_id = "homecare/${var.environment}/db-password"
}

locals {
  db_password = jsondecode(data.aws_secretsmanager_secret_version.db_password.secret_string)["password"]
}
```

## 7. IaC 检查清单

- [ ] Terraform 模块
- [ ] 环境配置
- [ ] 状态管理
- [ ] Ansible Role
- [ ] Playbook
- [ ] CI/CD 集成
- [ ] 环境隔离
- [ ] 命名规范
- [ ] 标签规范
- [ ] 敏感信息管理
- [ ] 变更审查
- [ ] 回滚方案

---

*基础设施即代码，让运维像写代码一样优雅。可复现、可版本化、可审查。*
