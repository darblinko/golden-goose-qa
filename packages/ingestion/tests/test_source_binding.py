"""Source-path binding helpers used by rename-safe sync reconciliation.

resolve_doc_keys_by_source_paths maps each deleted source path to the doc_key of
the live document ingested from it; rebind_source_path moves a document's binding
to the path it now occupies after a source-side rename. Both are exercised here
with a recording session so no database is required (the live path is covered by
tests/integration).
"""

from types import SimpleNamespace
from typing import Any, cast

from gg_ingestion.registry import rebind_source_path, resolve_doc_keys_by_source_paths
from sqlalchemy.ext.asyncio import AsyncSession


class _RecordingResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def __iter__(self) -> Any:
        return iter(self._rows)


class _RecordingSession:
    """Captures every SQL text and param dict, and returns preset rows."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, clause: object, params: dict[str, Any]) -> _RecordingResult:
        self.calls.append((str(clause), params))
        return _RecordingResult(self._rows)


async def test_resolve_maps_paths_to_doc_keys():
    session = _RecordingSession(
        [
            SimpleNamespace(source_path="a/SOP-1.docx", doc_key="SOP-1"),
            SimpleNamespace(source_path="a/SOP-2.docx", doc_key="SOP-2"),
        ]
    )
    result = await resolve_doc_keys_by_source_paths(
        cast(AsyncSession, session), ["a/SOP-1.docx", "a/SOP-2.docx", "a/orphan.docx"]
    )
    assert result == {"a/SOP-1.docx": "SOP-1", "a/SOP-2.docx": "SOP-2"}
    # Tombstoned documents are excluded, and the lookup is a single batched query.
    sql, params = session.calls[0]
    assert "deleted_at IS NULL" in sql
    assert params["source_paths"] == ["a/SOP-1.docx", "a/SOP-2.docx", "a/orphan.docx"]


async def test_resolve_short_circuits_on_empty_input():
    session = _RecordingSession([])
    result = await resolve_doc_keys_by_source_paths(cast(AsyncSession, session), [])
    assert result == {}
    assert session.calls == []  # no query issued for an empty batch


async def test_rebind_moves_the_binding_to_the_new_path():
    session = _RecordingSession([])
    await rebind_source_path(
        cast(AsyncSession, session),
        old_source_path="a/SOP-1.docx",
        new_source_path="b/SOP-1.docx",
    )
    sql, params = session.calls[0]
    assert "UPDATE app.document_versions" in sql
    assert "SET source_path = :new" in sql
    assert params == {"new": "b/SOP-1.docx", "old": "a/SOP-1.docx"}
