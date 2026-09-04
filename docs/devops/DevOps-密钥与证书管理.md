# DevOps-密钥与证书管理

> 本文档是家健镜系统DevOps-密钥与证书管理的完整设计说明。

## 1. 概述

### 1.1 设计目标

1. 密钥安全存储
2. 自动轮换
3. 访问控制
4. 审计日志
5. 证书自动续期

### 1.2 核心概念

| 概念 | 说明 |
| --- | --- |
| 密钥管理 | 加密密钥的生命周期管理 |
| 证书管理 | SSL/TLS 证书管理 |
| 密钥轮换 | 定期更换密钥 |

## 2. 密钥存储

```python
class SecretManager:
    def __init__(self, vault_client):
        self.vault = vault_client

    async def get_secret(self, path: str, key: str) -> str:
        secret = await self.vault.read(f"secret/data/{path}")
        return secret['data']['data'][key]

    async def create_secret(self, path: str, key: str, value: str):
        await self.vault.write(
            f"secret/data/{path}",
            data={key: value}
        )

    async def rotate_secret(self, path: str, key: str, new_value: str):
        # 1. 创建新版本
        await self.create_secret(path, key, new_value)
        # 2. 更新应用配置
        await self._notify_services(path, key)
```

## 3. 证书管理

```python
class CertificateManager:
    def __init__(self, acme_client):
        self.acme = acme_client

    async def issue_certificate(self, domain: str) -> Certificate:
        # 1. 创建订单
        order = await self.acme.new_order(domain)

        # 2. DNS 验证
        await self._dns_challenge(order)

        # 3. 获取证书
        cert = await self.acme.finalize_order(order)
        return cert

    async def renew_certificate(self, domain: str):
        cert = await self.get_certificate(domain)
        if cert.expires_in < 30:  # 30天内过期
            new_cert = await self.issue_certificate(domain)
            await self._deploy_certificate(new_cert)
```

## 4. 访问控制

```yaml
# Vault 策略
path "secret/data/homecare/production/*" {
  capabilities = ["read"]
}

path "secret/data/homecare/development/*" {
  capabilities = ["read", "create", "update"]
}
```

## 检查清单

- [ ] 密钥存储
- [ ] 密钥轮换
- [ ] 证书签发
- [ ] 证书续期
- [ ] 访问控制
- [ ] 审计日志

---

*DevOps-密钥与证书管理是系统的重要组成部分。*