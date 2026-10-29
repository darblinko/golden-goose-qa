from datetime import date, datetime
from decimal import Decimal
from typing import Any

from gg_retrieval.tools.models import ToolResult, plain_row, plain_value


def make_result(**overrides: Any) -> ToolResult:
    values: dict[str, Any] = {
        "tool": "warehouse",
        "title": "Open NCRs",
        "source": "registers.v_ncr_register",
        "query": "SELECT ...",
        "columns": ("ncr_id", "opened", "is_open"),
        "rows": (
            {"ncr_id": "NCR-001", "opened": "2025-03-01", "is_open": True},
            {"ncr_id": "NCR-002", "opened": None, "is_open": True},
        ),
    }
    values.update(overrides)
    return ToolResult(**values)


def test_plain_value_conversions():
    assert plain_value(date(2025, 3, 1)) == "2025-03-01"
    assert plain_value(datetime(2025, 3, 1, 12, 30)) == "2025-03-01T12:30:00"
    assert plain_value(Decimal("12.50")) == 12.5
    assert plain_value(None) is None
    assert plain_value(True) is True
    assert plain_value("text") == "text"


def test_plain_row_converts_every_value():
    row = plain_row({"opened": date(2025, 3, 1), "count": 3})
    assert row == {"opened": "2025-03-01", "count": 3}


def test_to_text_renders_header_columns_and_rows():
    text = make_result().to_text()
    lines = text.splitlines()
    assert lines[0] == "Open NCRs"
    assert lines[1] == "Source: registers.v_ncr_register"
    assert lines[2] == "ncr_id | opened | is_open"
    assert lines[3] == "NCR-001 | 2025-03-01 | True"
    assert lines[4] == "NCR-002 |  | True"  # None renders as empty, not "None"


def test_to_text_empty_and_truncated():
    assert "(no matching rows)" in make_result(rows=()).to_text()
    truncated = make_result(truncated=True).to_text()
    assert "(results truncated at 2 rows)" in truncated
