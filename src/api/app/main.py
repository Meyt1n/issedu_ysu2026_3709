import re
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import get_settings
from app.log_mask import install_log_mask
from app.request_context import reset_request_id, set_request_id
from app.routes import router

settings = get_settings()

if settings.log_mask_enabled:
    install_log_mask()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="一期本地优先家庭健康事件与授权骨架。视觉、规则和 LLM 适配器暂不可用。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    supplied = request.headers.get(settings.request_id_header, "").strip()
    request_id = (
        supplied
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", supplied)
        else str(uuid4())
    )
    request.state.request_id = request_id
    context_token = set_request_id(request_id)
    try:
        response = await call_next(request)
    finally:
        reset_request_id(context_token)
    response.headers[settings.request_id_header] = request_id
    return response


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError):
    if settings.app_env == "production":
        return JSONResponse(status_code=422, content={"detail": "UNPROCESSABLE_ENTITY"})
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def generic_error_handler(_request: Request, exc: Exception):
    if settings.app_env == "production":
        return JSONResponse(status_code=500, content={"detail": "INTERNAL_ERROR"})
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "version": __version__}


app.include_router(router)
