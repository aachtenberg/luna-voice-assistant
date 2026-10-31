"""Opt-in OpenTelemetry tracing.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set, and off means absent: this is the
only Luna module that names ``opentelemetry``, and it imports the SDK inside
``init_tracing()``. Until then ``span()`` hands back a no-op, nothing is exported
and no connection is opened. (FastAPI imports the API package regardless; that
alone does nothing.) Cut down from cfoperator's cfshared/tracing.py so the two
read alike in Tempo; voice/tracing.py is the other half of a Luna trace.

FastAPI makes the server span from the provider set here (see main.py), so
there is nothing below for inbound requests. Everything else nests under it.

What goes on a span is shapes, not text: provider, model, token counts, tool
names, durations, lengths. Never a transcript, a prompt, a completion, a tool's
arguments or its output. Those stay in the logs, whose lines carry the trace id,
so a trace still leads to them. Exceptions get the same treatment: a message can
quote anything, so a span records the class name only.

``span()`` makes its span current, which a generator cannot do across a
``yield``: Starlette resumes a sync generator on a pool thread with a copied
context at each step, so the span would be detached from a context it was never
attached to, and whatever ran next would lose its parent. Use ``detached_span()``
around a block that yields.
"""

import functools
import logging
import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Mapping, Optional

logger = logging.getLogger(__name__)

# Span attribute strings that are not free text (model and tool names) still
# come from config or from a model's output; cap them anyway.
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
        elif isinstance(value, (list, tuple)):
            value = [str(v)[:ATTR_LIMIT] for v in value if v is not None]
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
    to its class and is re-raised. Not for a block that yields: see the module
    docstring.
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
    entry, but never current itself, so nothing can nest under it and
    ``annotate()``/``mark_error()`` must be handed it. A generator closed
    early (voice hung up on a barge-in) ends it with ``luna.cancelled``."""
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


def traced(name: str, attributes: Optional[Mapping[str, Any]] = None,
           count_attr: Optional[str] = None):
    """Decorator form of ``span()``. With ``count_attr``, a sized result's
    length goes on the span under that name: how much, never what."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            with span(name, attributes):
                result = fn(*args, **kwargs)
                if count_attr and hasattr(result, '__len__'):
                    annotate({count_attr: len(result)})
                return result
        return inner
    return wrap


def _target(s):
    from opentelemetry import trace
    return s if s is not None else trace.get_current_span()


def annotate(attributes: Mapping[str, Any], s=None) -> None:
    """Set attributes on ``s``, else the current span; nothing while off.

    Lets a function add what it learned to the span its caller opened.
    """
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
    it: for a call that reports failure in its return value, as Luna's tools
    do. Class-shaped, like the exception path: a fixed name, never a message."""
    if _tracer is not None:
        _fail(_target(s), error_type)


def current_trace_id() -> Optional[str]:
    """The current trace's id as Tempo shows it, or None; for log lines."""
    if _tracer is None:
        return None
    from opentelemetry import trace
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, '032x') if context.is_valid else None
