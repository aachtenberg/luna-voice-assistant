"""Structured JSON logging for Loki compatibility."""

import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Format log records as JSON for Loki ingestion."""

    def format(self, record):
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "voice",
        }

        # Add extra fields if present
        if hasattr(record, "event"):
            log_obj["event"] = record.event
        if hasattr(record, "duration_ms"):
            log_obj["duration_ms"] = record.duration_ms
        if hasattr(record, "extra"):
            log_obj.update(record.extra)

        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def setup_logging(json_output: bool = True):
    """Configure logging with JSON or plain text output."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)

    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        ))

    root.addHandler(handler)
    return logging.getLogger("voice")


def get_logger(name: str = "voice"):
    """Get a logger instance."""
    return logging.getLogger(name)
