"""Domain errors and their RFC 9457 (problem+json) representation.

Every error the API returns has a stable machine-readable `code`, so clients
never have to parse human-readable messages.
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger()

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    title = "Bad request"

    def __init__(self, detail: str | None = None, *, code: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        if code:
            self.code = code


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"
    title = "Authentication required"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    title = "You do not have permission to perform this action"


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    title = "Resource not found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    title = "The request conflicts with the current state of the resource"


class BusinessRuleViolation(AppError):
    status_code = 422
    code = "business_rule_violation"
    title = "The request violates a business rule"


def _problem(
    request: Request, status: int, code: str, title: str, detail: str, **extra: Any
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://agencyos.dev/problems/{code}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
        "request_id": getattr(request.state, "request_id", None),
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        response = _problem(request, exc.status_code, exc.code, exc.title, exc.detail)
        if headers:
            response.headers.update(headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "field": ".".join(str(p) for p in e["loc"] if p != "body"),
                "message": e["msg"],
                "type": e["type"],
            }
            for e in exc.errors()
        ]
        return _problem(
            request, 422, "validation_error", "Validation failed",
            "One or more fields are invalid.", errors=errors,
        )  # fmt: skip

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _problem(request, exc.status_code, code, str(exc.detail), str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        # Never leak internals; the request_id lets support correlate with logs.
        return _problem(
            request, 500, "internal_error", "Internal server error",
            "An unexpected error occurred.",
        )  # fmt: skip
