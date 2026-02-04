"""Prometheus metrics for brain service."""

import time
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Request metrics
REQUESTS_TOTAL = Counter(
    'brain_requests_total',
    'Total number of requests to brain service',
    ['status']
)

REQUEST_DURATION = Histogram(
    'brain_request_duration_seconds',
    'Request duration in seconds',
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
)

# LLM metrics
LLM_CALLS_TOTAL = Counter(
    'brain_llm_calls_total',
    'Total LLM API calls',
    ['provider', 'model']
)

LLM_DURATION = Histogram(
    'brain_llm_duration_seconds',
    'LLM response time in seconds',
    ['provider'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
)

LLM_ERRORS = Counter(
    'brain_llm_errors_total',
    'LLM errors',
    ['provider', 'error_type']
)

# Tool metrics
TOOL_CALLS_TOTAL = Counter(
    'brain_tool_calls_total',
    'Total tool calls',
    ['tool_name']
)

TOOL_DURATION = Histogram(
    'brain_tool_duration_seconds',
    'Tool execution time',
    ['tool_name'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0]
)

TOOL_ERRORS = Counter(
    'brain_tool_errors_total',
    'Tool errors',
    ['tool_name']
)

# Current state
CURRENT_PROVIDER = Gauge(
    'brain_current_provider',
    'Current LLM provider (1=active)',
    ['provider']
)


def get_metrics():
    """Return metrics in Prometheus format."""
    return generate_latest()


def get_content_type():
    """Return Prometheus content type."""
    return CONTENT_TYPE_LATEST
