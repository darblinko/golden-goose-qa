"""Credentials in outbound request URLs never reach the JSON log.

httpx logs each request URL at INFO. openFDA only accepts its key as the
api_key query parameter, so the log formatter redacts sensitive parameters in
messages and in formatted exceptions."""

import io
import json
import logging
import sys

import httpx
import pytest
from gg_common.logging import JsonFormatter, redact_secrets

_KEY = "synthetic-secret-0123456789"


@pytest.fixture
def json_log():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    httpx_logger = logging.getLogger("httpx")
    previous_level = httpx_logger.level
    httpx_logger.addHandler(handler)
    httpx_logger.setLevel(logging.INFO)
    yield stream
    httpx_logger.removeHandler(handler)
    httpx_logger.setLevel(previous_level)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"GET https://x/y?api_key={_KEY}&limit=5", "GET https://x/y?api_key=[REDACTED]&limit=5"),
        (f"https://x/y?search=a&key={_KEY}", "https://x/y?search=a&key=[REDACTED]"),
        (f"https://x/y?API_KEY={_KEY} done", "https://x/y?API_KEY=[REDACTED] done"),
        (f"https://x/y?access_token={_KEY}", "https://x/y?access_token=[REDACTED]"),
        ("https://x/y?monkey=1&keyword=2", "https://x/y?monkey=1&keyword=2"),
    ],
)
def test_redact_secrets(text, expected):
    assert redact_secrets(text) == expected


async def test_httpx_request_log_redacts_query_key(json_log):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    async with httpx.AsyncClient(transport=transport) as client:
        await client.get(
            "https://api.fda.gov/device/event.json", params={"search": "x", "api_key": _KEY}
        )
    output = json_log.getvalue()
    assert "api.fda.gov" in output
    assert _KEY not in output
    assert "api_key=[REDACTED]" in json.loads(output.splitlines()[0])["message"]


def test_exception_text_is_redacted():
    formatter = JsonFormatter()
    try:
        raise RuntimeError(f"failed GET https://x/y?api_key={_KEY}")
    except RuntimeError:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", None, None)
        record.exc_info = sys.exc_info()
    entry = json.loads(formatter.format(record))
    assert _KEY not in entry["exception"]
    assert "api_key=[REDACTED]" in entry["exception"]
