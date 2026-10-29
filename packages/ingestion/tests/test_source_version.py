"""fetch_source_version resolves the exact version a citation names.

A citation to an obsolete revision must serve the bytes that were cited, not the
current effective version. The version-specific branch adds a `v.id = ...` gate;
without a version_id the query resolves the current version as before. These
tests exercise the SQL the resolver builds and the params it binds, using a
recording session so no database is required.
"""

from types import SimpleNamespace
from typing import Any, cast

from gg_ingestion.registry import fetch_source_version
from sqlalchemy.ext.asyncio import AsyncSession


class _RecordingResult:
    def __init__(self, row: object) -> None:
        self._row = row

    def first(self) -> object:
        return self._row


class _RecordingSession:
    """Captures the SQL text and bound params of the single SELECT, and returns
    a preset row from .first()."""

    def __init__(self, row: object) -> None:
        self._row = row
        self.sql: str = ""
        self.params: dict[str, Any] = {}

    async def execute(self, clause: object, params: dict[str, Any]) -> _RecordingResult:
        self.sql = str(clause)
        self.params = params
        return _RecordingResult(self._row)


def _row() -> SimpleNamespace:
    return SimpleNamespace(
        id="ver-abc",
        doc_key="SOP-004",
        doc_type="sop",
        title="CAPA",
        revision="B",
        file_format="pdf",
        content_hash="hash",
        object_key="key",
    )


async def test_version_id_adds_exact_version_gate():
    session = _RecordingSession(_row())
    result = await fetch_source_version(
        cast(AsyncSession, session), doc_key="SOP-004", version_id="ver-abc"
    )
    assert "v.id = CAST(:version_id AS uuid)" in session.sql
    assert session.params["version_id"] == "ver-abc"
    assert result is not None and result.version_id == "ver-abc"
    assert result.revision == "B"


async def test_without_version_id_resolves_current_version():
    session = _RecordingSession(_row())
    await fetch_source_version(cast(AsyncSession, session), doc_key="SOP-004")
    assert "v.id = CAST(:version_id AS uuid)" not in session.sql
    assert session.params["version_id"] is None


async def test_unknown_version_returns_none():
    session = _RecordingSession(None)
    result = await fetch_source_version(
        cast(AsyncSession, session), doc_key="SOP-004", version_id="does-not-exist"
    )
    assert result is None
