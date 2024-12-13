import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from loguru import logger
from starlette.responses import PlainTextResponse

from app.config import get_config
from app.mdl.http import get_http_client, warmup_http_client
from app.middleware import ProcessTimeMiddleware, RequestLogMiddleware
from app.model import ConfigModel, CustomHttpError
from app.routers import v2, v3

get_config().init_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(warmup_http_client())  # noqa: RUF006

    yield

    await get_http_client().aclose()


app = FastAPI(lifespan=lifespan)
app.include_router(v2.router)
app.include_router(v3.router)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(ProcessTimeMiddleware)
app.add_middleware(
    CorrelationIdMiddleware,
    header_name="X-Correlation-ID",
    generator=lambda: str(uuid4()),
)


@app.get("/")
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/config")
def provide_config():
    return get_config()


@app.patch("/config")
def update_config(config_model: ConfigModel):
    config = get_config()
    config.update(diagnose=config_model.diagnose)
    return config


# In Starlette, the Exception is special and is not included in normal exception handlers.
@app.exception_handler(Exception)
def exception_handler(request, exc: Exception):
    return PlainTextResponse(str(exc), status_code=500)


# In Starlette, the exceptions other than the Exception are not raised when call_next in the middleware.
@app.exception_handler(CustomHttpError)
def custom_http_error_handler(request, exc: CustomHttpError):
    with logger.contextualize(correlation_id=request.headers.get("X-Correlation-ID")):
        logger.opt(exception=exc).error("Request failed")
    return PlainTextResponse(str(exc), status_code=exc.status_code)
