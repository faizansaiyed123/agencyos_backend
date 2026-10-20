"""AgencyOS application entrypoint."""

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.modules.billing.router import router as billing_router
from app.modules.collab.router import router as collab_router
from app.modules.crm.router import router as crm_router
from app.modules.files.router import router as files_router
from app.modules.identity import jobs as identity_jobs
from app.modules.identity.router import router as identity_router
from app.modules.privacy.router import router as privacy_router
from app.modules.projects.router import router as projects_router
from app.modules.proposals import jobs as proposals_jobs
from app.modules.proposals.router import router as proposals_router
from app.modules.reporting.router import router as reporting_router
from app.modules.search.router import router as search_router
from app.modules.time.router import router as time_router
from app.platform import tracing
from app.platform import webhooks as webhooks_platform
from app.platform.flags_router import router as flags_router
from app.platform.webhooks_router import router as webhooks_router

configure_logging()
identity_jobs.register()
proposals_jobs.register()
webhooks_platform.register()
tracing.init_from_settings()
log = structlog.get_logger()
settings = get_settings()

app = FastAPI(title="AgencyOS API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)


app.middleware("http")(tracing.trace_request)


@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
    response.headers["permissions-policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.env == "prod":
        response.headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.monotonic()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.clear_contextvars()
    response.headers["x-request-id"] = request_id
    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.monotonic() - start) * 1000, 1),
    )
    return response


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"])
def readyz() -> dict[str, str]:
    from sqlalchemy import text

    from app.core.db import get_engine

    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ready"}


app.include_router(identity_router, prefix="/api/v1")
app.include_router(crm_router, prefix="/api/v1")
app.include_router(proposals_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(time_router, prefix="/api/v1")
app.include_router(billing_router, prefix="/api/v1")
app.include_router(collab_router, prefix="/api/v1")
for _r in (files_router, privacy_router, reporting_router, search_router, flags_router):
    app.include_router(_r, prefix="/api/v1")
