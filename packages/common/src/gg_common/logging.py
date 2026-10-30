"""Structured JSON logging on the standard library only."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from gg_common.settings import AppSettings, effective_settings_summary

# Query parameters that carry credentials. httpx logs every request URL at INFO
# and its exceptions embed the URL, so values are masked before output.
_SENSITIVE_QUERY_RE = re.compile(
    r"([?&](?:api_key|apikey|key|access_token|token|client_secret)=)[^&\s\"'#]+",
    re.IGNORECASE,
)


def redact_secrets(text: str) -> str:
    """Mask credential-bearing query parameter values in text."""
    return _SENSITIVE_QUERY_RE.sub(r"\1[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secrets(record.getMessage()),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = redact_secrets(self.formatException(record.exc_info))
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            entry.update(extra)
        return json.dumps(entry, default=str)


def configure_logging(settings: AppSettings) -> None:
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]


def log_effective_settings(settings: AppSettings, logger_name: str = "gg.startup") -> None:
    logging.getLogger(logger_name).info(
        "effective configuration",
        extra={"extra_fields": {"config": effective_settings_summary(settings)}},
    )
