"""Eval history: one JSONL line per battery run, so trends survive across
runs and the dashboard can plot them without a database."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def current_git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, timeout=10
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode().strip() or None


def make_record(
    metrics: dict[str, Any],
    *,
    smoke: bool,
    git_sha: str | None,
    schema_version: int | None = None,
) -> dict[str, Any]:
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
        "schema_version": schema_version,
        "smoke": smoke,
        "metrics": metrics,
    }


def prune_incomparable(
    records: list[dict[str, Any]], schema_version: int | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split restored history into records that share the current QA
    schema_version (kept — the trend is comparable) and those that do not
    (dropped — an older schema or an unstamped run whose metrics measure a
    different golden set). When the current schema_version is unknown there is
    no basis to call any record stale, so nothing is dropped."""
    if schema_version is None:
        return list(records), []
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for record in records:
        (kept if record.get("schema_version") == schema_version else dropped).append(record)
    return kept, dropped


def append_history(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def overwrite_history(path: Path, records: list[dict[str, Any]]) -> None:
    """Rewrite the history file with exactly these records (used after pruning
    stale restored runs — append alone cannot remove them)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for record in records:
            fh.write(json.dumps(record, sort_keys=True) + "\n")


def load_history(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records
