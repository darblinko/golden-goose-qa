"""Self-contained HTML trend dashboard over the eval history.

One static file, no external assets (inline CSS + inline SVG sparklines), so
it works as a CI artifact, from file://, or pinned in a wiki. Each tracked
metric shows its latest value, range, and a sparkline across runs.
"""

import html
from typing import Any

# (label, dotted path into record["metrics"], higher_is_better)
TRACKED_METRICS: tuple[tuple[str, str, bool], ...] = (
    ("Retrieval recall@10", "retrieval.recall@10", True),
    ("Retrieval MRR@10", "retrieval.mrr@10", True),
    ("Grounded rate", "answers.grounded_rate", True),
    ("Citation precision", "answers.citation_precision", True),
    ("Citation recall", "answers.citation_recall", True),
    ("Answer support", "answers.support", True),
    ("Routing accuracy", "routing.accuracy", True),
    ("Noise degradation", "noise.degradation", False),
    ("Noise intrusion", "noise.intrusion", False),
)

_SPARK_WIDTH = 220
_SPARK_HEIGHT = 44
_PAD = 4


def metric_series(records: list[dict[str, Any]], path: str) -> list[float | None]:
    series: list[float | None] = []
    for record in records:
        node: Any = record.get("metrics", {})
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        series.append(float(node) if isinstance(node, (int, float)) else None)
    return series


def sparkline(series: list[float | None]) -> str:
    points = [(i, v) for i, v in enumerate(series) if v is not None]
    if not points:
        return "<svg></svg>"
    values = [v for _, v in points]
    low, high = min(values), max(values)
    spread = (high - low) or 1.0
    span = (len(series) - 1) or 1
    coords = []
    for i, v in points:
        x = _PAD + (i / span) * (_SPARK_WIDTH - 2 * _PAD)
        y = _PAD + (1 - (v - low) / spread) * (_SPARK_HEIGHT - 2 * _PAD)
        coords.append(f"{x:.1f},{y:.1f}")
    last_x, last_y = coords[-1].split(",")
    return (
        f'<svg width="{_SPARK_WIDTH}" height="{_SPARK_HEIGHT}" '
        f'viewBox="0 0 {_SPARK_WIDTH} {_SPARK_HEIGHT}">'
        f'<polyline fill="none" stroke="#2563eb" stroke-width="1.5" '
        f'points="{" ".join(coords)}"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.5" fill="#2563eb"/></svg>'
    )


def _metric_row(label: str, series: list[float | None], higher_is_better: bool) -> str:
    values = [v for v in series if v is not None]
    if not values:
        return ""
    latest = values[-1]
    best = max(values) if higher_is_better else min(values)
    at_best = "best" if latest == best else ""
    return (
        f"<tr><td>{html.escape(label)}</td>"
        f'<td class="value {at_best}">{latest:.4f}</td>'
        f"<td>{min(values):.4f} &ndash; {max(values):.4f}</td>"
        f"<td>{sparkline(series)}</td></tr>"
    )


def render_dashboard(records: list[dict[str, Any]]) -> str:
    rows = "".join(
        _metric_row(label, metric_series(records, path), higher)
        for label, path, higher in TRACKED_METRICS
    )
    latest = records[-1] if records else {}
    stamp = html.escape(str(latest.get("created_at", "never")))
    sha = html.escape(str(latest.get("git_sha") or "unknown"))
    schema = html.escape(str(latest.get("schema_version") or "unknown"))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Golden Goose eval trends</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1f2937; }}
h1 {{ font-size: 1.3rem; }}
p.meta {{ color: #6b7280; }}
table {{ border-collapse: collapse; }}
td, th {{ padding: 0.4rem 1rem; border-bottom: 1px solid #e5e7eb; text-align: left; }}
td.value {{ font-variant-numeric: tabular-nums; font-weight: 600; }}
td.value.best {{ color: #15803d; }}
</style>
</head>
<body>
<h1>Golden Goose eval trends</h1>
<p class="meta">{len(records)} runs · latest {stamp} · commit {sha} · QA schema {schema}</p>
<table>
<tr><th>Metric</th><th>Latest</th><th>Range</th><th>Trend</th></tr>
{rows}
</table>
</body>
</html>
"""
