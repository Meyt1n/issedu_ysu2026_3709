# 后端文件存储与CDN设计

> 本文档是家健镜系统后端文件存储与 CDN 的完整设计说明，覆盖存储方案、文件上传、CDN 加速、图片处理、安全控制。

## 1. 概述

### 1.1 设计目标

1. 文件上传成功率 > 99%
2. 下载延迟 < 200ms
3. 支持大文件分片上传
4. 图片自动处理
5. 安全防泄漏

### 1.2 存储方案

| 存储类型 | 用途 | 存储类 |
| --- | --- | --- |
| 用户头像 | 小图片 | 标准存储 |
| 健康报告 | PDF | 标准存储 |
| 医学影像 | 大文件 | 低频访问 |
| 备份文件 | 归档 | 归档存储 |
| 静态资源 | JS/CSS | CDN 缓存 |

## 2. 对象存储

### 2.1 S3 兼容存储

```python
import boto3
from botocore.config import Config

class ObjectStorage:
    def __init__(self, endpoint_url, access_key, secret_key, bucket):
        self.client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version='s3v4'),
        )
        self.bucket = bucket

    async def upload_file(self, key: str, data: bytes, content_type: str = None):
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type

        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            **extra_args,
        )
        return key

    async def download_file(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response['Body'].read()

    async def delete_file(self, key: str):
        self.client.delete_object(Bucket=self.bucket, Key=key)

    async def get_presigned_url(self, key: str, expires: int = 3600) -> str:
        return self.client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket, 'Key': key},
            ExpiresIn=expires,
        )
```

### 2.2 文件命名

```python
import uuid
from datetime import datetime

class FileNamer:
    @staticmethod
    def generate_key(user_id: str, file_type: str, extension: str) -> str:
        date_path = datetime.now().strftime('%Y/%m/%d')
        unique_id = uuid.uuid4().hex
        return f"{file_type}/{user_id}/{date_path}/{unique_id}.{extension}"

    @staticmethod
    def generate_avatar_key(user_id: str) -> str:
        return f"avatars/{user_id}.jpg"

    @staticmethod
    def generate_report_key(user_id: str, report_id: str) -> str:
        return f"reports/{user_id}/{report_id}.pdf"
```

## 3. 文件上传

### 3.1 普通上传

```python
from fastapi import UploadFile, HTTPException

class FileUploadService:
    def __init__(self, storage: ObjectStorage):
        self.storage = storage
        self.allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'application/pdf'}
        self.max_size = 10 * 1024 * 1024  # 10MB

    async def upload(self, file: UploadFile, user_id: str, file_type: str) -> dict:
        # 验证文件类型
        if file.content_type not in self.allowed_types:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file.content_type}")

        # 验证文件大小
        content = await file.read()
        if len(content) > self.max_size:
            raise HTTPException(status_code=400, detail="文件大小超过限制")

        # 生成文件名
        extension = file.filename.split('.')[-1].lower()
        key = FileNamer.generate_key(user_id, file_type, extension)

        # 上传
        await self.storage.upload_file(key, content, file.content_type)

        return {
            "key": key,
            "url": f"/files/{key}",
            "size": len(content),
            "content_type": file.content_type,
        }
```

### 3.2 分片上传

```python
class MultipartUploadService:
    def __init__(self, storage: ObjectStorage):
        self.storage = storage
        self.chunk_size = 5 * 1024 * 1024  # 5MB

    async def initiate_upload(self, key: str) -> str:
        response = self.storage.client.create_multipart_upload(
            Bucket=self.storage.bucket,
            Key=key,
        )
        return response['UploadId']

    async def upload_part(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        data: bytes,
    ) -> dict:
        response = self.storage.client.upload_part(
            Bucket=self.storage.bucket,
            Key=key,
            PartNumber=part_number,
            UploadId=upload_id,
            Body=data,
        )
        return {
            "PartNumber": part_number,
            "ETag": response['ETag'],
        }

    async def complete_upload(self, key: str, upload_id: str, parts: list):
        self.storage.client.complete_multipart_upload(
            Bucket=self.storage.bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    async def abort_upload(self, key: str, upload_id: str):
        self.storage.client.abort_multipart_upload(
            Bucket=self.storage.bucket,
            Key=key,
            UploadId=upload_id,
        )
```

### 3.3 断点续传

```python
class ResumableUpload:
    def __init__(self, storage: ObjectStorage):
        self.storage = storage
        self.upload_sessions = {}

    def create_session(self, key: str, total_size: int) -> str:
        session_id = uuid.uuid4().hex
        self.upload_sessions[session_id] = {
            "key": key,
            "total_size": total_size,
            "uploaded_parts": [],
            "upload_id": None,
        }
        return session_id

    async def upload_chunk(self, session_id: str, chunk_number: int, data: bytes):
        session = self.upload_sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="上传会话不存在")

        # 初始化分片上传
        if not session["upload_id"]:
            session["upload_id"] = await self._initiate(session["key"])

        # 上传分片
        part = await self.storage.upload_part(
            session["key"],
            session["upload_id"],
            chunk_number,
            data,
        )
        session["uploaded_parts"].append(part)

    async def complete(self, session_id: str):
        session = self.upload_sessions.pop(session_id)
        await self.storage.complete_upload(
            session["key"],
            session["upload_id"],
            sorted(session["uploaded_parts"], key=lambda x: x["PartNumber"]),
        )
```

## 4. CDN 加速

### 4.1 CDN 配置

```python
class CDNService:
    def __init__(self, cdn_domain: str, storage: ObjectStorage):
        self.cdn_domain = cdn_domain
        self.storage = storage

    def get_url(self, key: str) -> str:
        return f"https://{self.cdn_domain}/{key}"

    async def purge_cache(self, keys: list[str]):
        # 刷新 CDN 缓存
        for key in keys:
            self._purge_single(key)

    def _purge_single(self, key: str):
        # 调用 CDN API 刷新
        pass

    async def prefetch(self, keys: list[str]):
        # CDN 预热
        for key in keys:
            self._prefetch_single(key)
```

### 4.2 缓存策略

```python
class CachePolicy:
    @staticmethod
    def get_cache_headers(file_type: str) -> dict:
        policies = {
            "image": {
                "Cache-Control": "public, max-age=31536000, immutable",
                "CDN-Cache-Control": "max-age=31536000",
            },
            "pdf": {
                "Cache-Control": "public, max-age=86400",
                "CDN-Cache-Control": "max-age=86400",
            },
            "video": {
                "Cache-Control": "public, max-age=31536000",
                "CDN-Cache-Control": "max-age=31536000",
            },
            "default": {
                "Cache-Control": "public, max-age=3600",
                "CDN-Cache-Control": "max-age=3600",
            },
        }
        return policies.get(file_type, policies["default"])
```

## 5. 图片处理

### 5.1 图片压缩

```python
from PIL import Image
import io

class ImageProcessor:
    @staticmethod
    def compress(image_data: bytes, quality: int = 80, max_width: int = 1920) -> bytes:
        image = Image.open(io.BytesIO(image_data))

        # 调整大小
        if image.width > max_width:
            ratio = max_width / image.width
            new_height = int(image.height * ratio)
            image = image.resize((max_width, new_height), Image.LANCZOS)

        # 转换为 WebP
        output = io.BytesIO()
        image.save(output, format='WebP', quality=quality)
        return output.getvalue()

    @staticmethod
    def generate_thumbnail(image_data: bytes, size: int = 200) -> bytes:
        image = Image.open(io.BytesIO(image_data))
        image.thumbnail((size, size))
        output = io.BytesIO()
        image.save(output, format='WebP', quality=70)
        return output.getvalue()
```

### 5.2 图片裁剪

```python
class ImageCropper:
    @staticmethod
    def crop(image_data: bytes, x: int, y: int, width: int, height: int) -> bytes:
        image = Image.open(io.BytesIO(image_data))
        cropped = image.crop((x, y, x + width, y + height))
        output = io.BytesIO()
        cropped.save(output, format='WebP', quality=85)
        return output.getvalue()

    @staticmethod
    def avatar_crop(image_data: bytes) -> bytes:
        image = Image.open(io.BytesIO(image_data))
        width, height = image.size
        size = min(width, height)
        left = (width - size) // 2
        top = (height - size) // 2
        cropped = image.crop((left, top, left + size, top + size))
        cropped = cropped.resize((400, 400), Image.LANCZOS)
        output = io.BytesIO()
        cropped.save(output, format='WebP', quality=85)
        return output.getvalue()
```

### 5.3 图片水印

```python
class ImageWatermark:
    @staticmethod
    def add_watermark(image_data: bytes, text: str) -> bytes:
        from PIL import ImageDraw, ImageFont

        image = Image.open(io.BytesIO(image_data)).convert('RGBA')
        overlay = Image.new('RGBA', image.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)

        # 添加半透明水印
        font = ImageFont.truetype('arial.ttf', 36)
        draw.text((10, 10), text, fill=(255, 255, 255, 128), font=font)

        watermarked = Image.alpha_composite(image, overlay)
        output = io.BytesIO()
        watermarked.convert('RGB').save(output, format='JPEG', quality=90)
        return output.getvalue()
```

## 6. 安全控制

### 6.1 访问控制

```python
class FileAccessControl:
    def __init__(self, storage: ObjectStorage):
        self.storage = storage

    async def get_signed_url(self, key: str, user_id: str, expires: int = 3600) -> str:
        # 验证用户权限
        if not await self._has_access(key, user_id):
            raise HTTPException(status_code=403, detail="没有访问权限")

        return await self.storage.get_presigned_url(key, expires)

    async def _has_access(self, key: str, user_id: str) -> bool:
        # 检查文件归属
        if key.startswith(f"users/{user_id}/"):
            return True

        # 检查共享权限
        return await self._check_shared_permission(key, user_id)

    async def _check_shared_permission(self, key: str, user_id: str) -> bool:
        # 查询数据库中的共享记录
        pass
```

### 6.2 病毒扫描

```python
class VirusScanner:
    def __init__(self, clamav_host: str):
        self.clamav_host = clamav_host

    async def scan(self, file_data: bytes) -> bool:
        # 调用 ClamAV 扫描
        try:
            result = await self._scan_with_clamav(file_data)
            return result['clean']
        except Exception as e:
            # 扫描失败时默认拒绝（安全优先）
            return False

    async def _scan_with_clamav(self, file_data: bytes) -> dict:
        # 使用 pyclamd 或 HTTP API
        pass
```

### 6.3 文件类型验证

```python
class FileValidator:
    MAGIC_NUMBERS = {
        b'ÿØÿ': 'image/jpeg',
        b'PNG

': 'image/png',
        b'RIFF': 'image/webp',
        b'%PDF': 'application/pdf',
    }

    @classmethod
    def validate(cls, file_data: bytes, expected_type: str) -> bool:
        for magic, file_type in cls.MAGIC_NUMBERS.items():
            if file_data.startswith(magic):
                return file_type == expected_type
        return False
```

## 7. 文件管理

### 7.1 文件元数据

```python
class FileMetadata:
    def __init__(self, db):
        self.db = db

    async def save_metadata(self, key: str, metadata: dict):
        await self.db.execute(
            '''INSERT INTO files (key, user_id, filename, content_type, size, created_at)
               VALUES ($1, $2, $3, $4, $5, NOW())''',
            key,
            metadata['user_id'],
            metadata['filename'],
            metadata['content_type'],
            metadata['size'],
        )

    async def get_metadata(self, key: str) -> dict:
        return await self.db.fetchone(
            "SELECT * FROM files WHERE key = $1",
            key,
        )

    async def delete_metadata(self, key: str):
        await self.db.execute("DELETE FROM files WHERE key = $1", key)
```

### 7.2 生命周期管理

```python
class FileLifecycle:
    def __init__(self, storage: ObjectStorage):
        self.storage = storage

    async def cleanup_temp_files(self):
        # 清理临时文件（超过24小时）
        temp_files = await self._get_temp_files()
        for key in temp_files:
            await self.storage.delete_file(key)

    async def archive_old_files(self, days: int = 90):
        # 归档旧文件到低频存储
        old_files = await self._get_old_files(days)
        for key in old_files:
            await self._change_storage_class(key, 'STANDARD_IA')
```

## 8. 文件存储检查清单

- [ ] 对象存储
- [ ] 文件命名
- [ ] 普通上传
- [ ] 分片上传
- [ ] 断点续传
- [ ] CDN 加速
- [ ] 缓存策略
- [ ] 图片压缩
- [ ] 图片裁剪
- [ ] 访问控制
- [ ] 病毒扫描
- [ ] 生命周期管理

---

*高效的文件存储是内容分发的基础。安全上传、CDN 加速、智能处理，让文件管理简单可靠。*
