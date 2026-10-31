"""Opt-in OpenTelemetry tracing: the voice half of a Luna trace.

One trace per conversation, rooted here at the wake word. The W3C traceparent on
each request to the brain carries it across; brain/tracing.py continues it.

Same contract as that module, which holds the reasoning. Off unless
OTEL_EXPORTER_OTLP_ENDPOINT is set, and off means absent: this is the only module
that names ``opentelemetry``, and it imports the SDK inside ``init_tracing()``.
Spans carry shapes, not text: never a transcript or a response, which stay in
the log lines that carry the trace id.

The context lives in a contextvar, so a thread starts without it. A thread that
should join the trace runs under ``contextvars.copy_context().run``. And
``span()`` is not for a block that yields: ``detached_span()`` is.
"""

import functools
import logging
import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Mapping, Optional

logger = logging.getLogger(__name__)

ATTR_LIMIT = 256

_tracer = None


class _NoopSpan:
    """What ``span()`` yields while tracing is off: every call does nothing."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_attributes(self, attributes: Mapping[str, Any]) -> None:
        pass

    def is_recording(self) -> bool:
        return False


_NOOP = _NoopSpan()


def init_tracing(default_service_name: str) -> bool:
    """Start exporting spans if OTEL_EXPORTER_OTLP_ENDPOINT is set.

    The exporter and resource read the standard OTEL_* variables themselves.
    Returns whether tracing is on. A missing SDK is a warning, never a crash:
    Luna runs untraced rather than not at all.
    """
    global _tracer
    if _tracer is not None:
        return True
    endpoint = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT')
    if not endpoint:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        logger.warning(f"OTEL_EXPORTER_OTLP_ENDPOINT is set but the OpenTelemetry "
                       f"SDK is not installed ({e}); running untraced")
        return False

    service_name = os.getenv('OTEL_SERVICE_NAME') or default_service_name
    provider = TracerProvider(resource=Resource.create({'service.name': service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _tracer = provider.get_tracer('luna')
    logger.info(f"Exporting spans as service.name={service_name} to {endpoint}")
    return True


def _clean(attributes: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Drop None values and clip strings; OTel rejects None outright."""
    out = {}
    for key, value in (attributes or {}).items():
        if value is None:
            continue
        if isinstance(value, str) and len(value) > ATTR_LIMIT:
            value = value[:ATTR_LIMIT] + '…'
        out[key] = value
    return out


def _kind(kind: Optional[str]):
    from opentelemetry.trace import SpanKind
    return SpanKind[kind.upper()] if kind else SpanKind.INTERNAL


def _fail(s, error_type: str) -> None:
    from opentelemetry.trace import Status, StatusCode
    if s.is_recording():
        s.set_attribute('error.type', error_type)
        s.set_status(Status(StatusCode.ERROR, error_type))


@contextmanager
def span(name: str, attributes: Optional[Mapping[str, Any]] = None,
         kind: Optional[str] = None) -> Iterator[Any]:
    """A current span around the block, or a no-op while tracing is off.

    An exception leaving the block marks the span ERROR with ``error.type`` set
    to its class and is re-raised.
    """
    if _tracer is None:
        yield _NOOP
        return
    with _tracer.start_as_current_span(
            name[:ATTR_LIMIT], kind=_kind(kind), attributes=_clean(attributes),
            record_exception=False, set_status_on_exception=False) as s:
        try:
            yield s
        except Exception as e:
            _fail(s, type(e).__name__)
            raise


@contextmanager
def detached_span(name: str, attributes: Optional[Mapping[str, Any]] = None,
                  kind: Optional[str] = None) -> Iterator[Any]:
    """``span()`` for a block that yields: a child of whatever is current on
    entry, but never current itself, so ``annotate()``/``mark_error()``/
    ``inject()`` must be handed it. A generator closed early (barge-in dropped
    the answer) ends it with ``luna.cancelled``."""
    if _tracer is None:
        yield _NOOP
        return
    s = _tracer.start_span(name[:ATTR_LIMIT], kind=_kind(kind), attributes=_clean(attributes))
    try:
        yield s
    except GeneratorExit:
        s.set_attribute('luna.cancelled', True)
        raise
    except Exception as e:
        _fail(s, type(e).__name__)
        raise
    finally:
        s.end()


def traced(name: str, kind: Optional[str] = None):
    """Decorator form of ``span()``."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            with span(name, kind=kind):
                return fn(*args, **kwargs)
        return inner
    return wrap


def _target(s):
    from opentelemetry import trace
    return s if s is not None else trace.get_current_span()


def annotate(attributes: Mapping[str, Any], s=None) -> None:
    """Set attributes on ``s``, else the current span; nothing while off."""
    if _tracer is None:
        return
    target = _target(s)
    if target.is_recording():
        target.set_attributes(_clean(attributes))


def event(name: str, attributes: Optional[Mapping[str, Any]] = None) -> None:
    """Mark a moment on the current span; nothing while off."""
    if _tracer is None:
        return
    target = _target(None)
    if target.is_recording():
        target.add_event(name, _clean(attributes))


def mark_error(error_type: str, s=None) -> None:
    """Mark ``s``, else the current span, failed without an exception leaving
    it. Class-shaped, like the exception path: a fixed name, never a message."""
    if _tracer is not None:
        _fail(_target(s), error_type)


def inject(headers: Dict[str, str], s=None) -> Dict[str, str]:
    """Put the W3C ``traceparent`` of ``s``, else the current span, on outbound
    headers, so the brain continues this trace. Nothing while off."""
    if _tracer is not None:
        from opentelemetry.propagate import inject as _inject
        from opentelemetry.trace import set_span_in_context
        _inject(headers, context=set_span_in_context(s) if s is not None else None)
    return headers


def current_trace_id() -> Optional[str]:
    """The current trace's id as Tempo shows it, or None; for log lines."""
    if _tracer is None:
        return None
    from opentelemetry import trace
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, '032x') if context.is_valid else None
