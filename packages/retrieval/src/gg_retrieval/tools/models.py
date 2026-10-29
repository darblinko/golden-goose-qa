"""Shared result shape for the structured tools (SQL, graph, file).

Rows are plain JSON-safe values so results survive the agent checkpointer,
and to_text() renders the evidence the generator reads — a tool result plays
the same role as a retrieved parent chunk in the citation machinery.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


def plain_value(value: Any) -> Any:
    """Coerce driver-specific values (dates, decimals) to JSON-safe ones."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def plain_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: plain_value(value) for key, value in row.items()}


@dataclass(frozen=True)
class ToolResult:
    tool: str  # "warehouse" | "graph_walk" | "file_query"
    title: str
    source: str  # human-readable citation of where the rows came from
    query: str  # the executed SQL / Cypher / call, for the audit trail
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    truncated: bool = False
    source_doc_keys: tuple[str, ...] = field(default=())
    # True when the anchor entity a lookup was addressed to (a document,
    # requirement, or supplier) does not exist in the corpus. An empty result
    # for a missing anchor is honest "not in corpus," never grounded evidence —
    # distinct from an empty set (e.g. no open NCRs), which is a real answer.
    anchor_missing: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.rows

    def to_text(self) -> str:
        lines = [self.title, f"Source: {self.source}"]
        if self.is_empty:
            lines.append("(no matching rows)")
            return "\n".join(lines)
        lines.append(" | ".join(self.columns))
        for row in self.rows:
            lines.append(" | ".join(_cell(row.get(column)) for column in self.columns))
        if self.truncated:
            lines.append(f"(results truncated at {len(self.rows)} rows)")
        return "\n".join(lines)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(plain_value(value))
