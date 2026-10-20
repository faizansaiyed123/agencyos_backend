"""OpenTelemetry tracing — off by default (AGENCYOS_OTEL_ENABLED=true to enable).

One server span per request, named `METHOD /route/{template}` (never the raw path, so
IDs do not explode metric cardinality), continuing an incoming W3C `traceparent` when
present. The trace id is echoed as `x-trace-id` and bound into every log line, so a
slow request found in the tracing UI can be matched to its logs and vice versa.
"""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from app.core.config import get_settings

_tracer: Tracer | None = None


def configure(exporter: SpanExporter | None = None, *, simple: bool = False) -> None:
    """Install a tracer provider. `exporter=None` builds one from settings. Tests pass
    an in-memory exporter with simple=True so spans are exported synchronously."""
    global _tracer  # noqa: PLW0603
    s = get_settings()
    if exporter is None:
        if s.otel_exporter == "otlp" and s.otel_otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=s.otel_otlp_endpoint)
        else:
            exporter = ConsoleSpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": s.otel_service_name}))
    provider.add_span_processor(
        SimpleSpanProcessor(exporter) if simple else BatchSpanProcessor(exporter)
    )
    _tracer = provider.get_tracer("agencyos")


def disable() -> None:
    global _tracer  # noqa: PLW0603
    _tracer = None


def init_from_settings() -> None:
    if get_settings().otel_enabled:
        configure()


async def trace_request(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if _tracer is None:
        return await call_next(request)
    ctx = propagate.extract(dict(request.headers))
    token = otel_context.attach(ctx)
    try:
        with _tracer.start_as_current_span(
            f"{request.method} {request.url.path}", kind=SpanKind.SERVER
        ) as span:
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("url.path", request.url.path)
            trace_id = format(span.get_span_context().trace_id, "032x")
            structlog.contextvars.bind_contextvars(trace_id=trace_id)
            try:
                response = await call_next(request)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR))
                raise
            template = request.url.path
            for name, value in request.path_params.items():
                template = template.replace(str(value), "{" + name + "}")
            if request.path_params:
                span.update_name(f"{request.method} {template}")
            span.set_attribute("http.route", template)
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 500:
                span.set_status(Status(StatusCode.ERROR))
            response.headers["x-trace-id"] = trace_id
            return response
    finally:
        otel_context.detach(token)


__all__ = ["configure", "disable", "init_from_settings", "trace", "trace_request"]
