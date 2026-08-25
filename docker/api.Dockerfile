FROM python:3.11-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.6.5 \
    && uv sync --frozen --no-dev

COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
# 知识爬虫（/knowledge/crawl/*）依赖仓库内的白名单与离线夹具；缺少它们时
# 容器内爬虫接口会以 KNOWLEDGE_CRAWL_CONFIG_MISSING 降级而不是可用。
# staging 与 approved/incoming 为运行期产物，写入容器文件系统（教学演示用途）。
COPY docs/knowledge ./docs/knowledge

ENV PYTHONPATH=/app/src/api:/app/src

CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000"]
