"""Result shape for external data tools.

An ExternalResult is deliberately not a ToolResult: provenance is typed as
"external" and to_text() opens with an EXTERNAL SOURCE banner, so external
evidence can never silently pass as a QMS citation anywhere downstream —
the generator sees the banner, the citation panel sees the provenance.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExternalResult:
    tool: str  # "openfda_maude" | "openfda_recalls" | ...
    title: str
    source: str  # human-readable API name, e.g. "openFDA device/event API"
    query: str  # what was asked, for the audit trail
    url: str  # the request URL (never contains credentials)
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    truncated: bool = False
    # The source-reported count of all matching records (openFDA meta.results
    # .total). The rows are only one capped page, so this is the authoritative
    # figure for any rate or comparison. None when the source reports no total.
    total: int | None = None
    provenance: str = "external"

    @property
    def is_empty(self) -> bool:
        return not self.rows

    def to_text(self) -> str:
        lines = [
            f"EXTERNAL SOURCE (not QMS evidence): {self.title}",
            f"Source: {self.source}",
            f"Query: {self.query}",
        ]
        if self.total is not None:
            lines.append(f"Total matching records reported by the source: {self.total}")
        if self.is_empty:
            lines.append("(no matching records)")
            return "\n".join(lines)
        lines.append(" | ".join(self.columns))
        for row in self.rows:
            lines.append(" | ".join(_cell(row.get(column)) for column in self.columns))
        if self.truncated:
            lines.append(f"(results truncated at {len(self.rows)} records)")
        return "\n".join(lines)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
