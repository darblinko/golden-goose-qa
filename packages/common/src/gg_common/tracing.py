"""OpenTelemetry tracing behind one seam, exporting to Arize Phoenix.

The global OTel tracer provider is never installed: the provider lives in
this module, so tests can configure and reset it freely and an unconfigured
process gets the API's no-op tracer. Instrumentation is therefore always safe
to leave in place — `span()` and `traced()` cost nothing until
`configure_tracing()` enables export.
"""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)

from gg_common.settings import TracingSettings

P = ParamSpec("P")
R = TypeVar("R")

_provider: TracerProvider | None = None


def configure_tracing(settings: TracingSettings, *, exporter: SpanExporter | None = None) -> None:
    """Install a tracer provider exporting OTLP/HTTP to settings.endpoint.
    No-op when disabled. Tests pass their own exporter, which is delivered
    synchronously instead of batched."""
    global _provider
    reset_tracing()
    if not settings.enabled:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": settings.service_name}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.endpoint))
        )
    _provider = provider


def reset_tracing() -> None:
    """Flush and drop the provider; spans become no-ops again."""
    global _provider
    if _provider is not None:
        _provider.shutdown()
    _provider = None


def _tracer() -> trace.Tracer:
    if _provider is not None:
        return _provider.get_tracer("gg")
    return trace.get_tracer("gg")


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """Start a span that is current for the enclosed block."""
    with _tracer().start_as_current_span(name) as current:
        set_span_attributes(current, **attributes)
        yield current


def set_span_attributes(target: trace.Span | None = None, **attributes: Any) -> None:
    """Attach attributes, namespaced under gg.*, to a span (default: the
    current one). None values are dropped; non-primitive values stringify."""
    resolved = target if target is not None else trace.get_current_span()
    for key, value in attributes.items():
        if value is None:
            continue
        if not isinstance(value, bool | int | float | str):
            value = str(value)
        resolved.set_attribute(f"gg.{key}", value)


def traced(name: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Wrap an async callable in a span of the given name."""

    def decorate(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with span(name):
                return await func(*args, **kwargs)

        return wrapper

    return decorate
