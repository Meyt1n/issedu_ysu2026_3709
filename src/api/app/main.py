from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import get_settings
from app.routes import router

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="一期本地优先家庭健康事件与授权骨架。视觉、规则和 LLM 适配器暂不可用。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get(settings.request_id_header, str(uuid4()))
    response = await call_next(request)
    response.headers[settings.request_id_header] = request_id
    return response


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "version": __version__}


app.include_router(router)
