"""register_version serializes concurrent ingests of one document key.

The version-existence check is a read-then-write (SELECT the content hash, INSERT
if absent). Two concurrent ingests of the same document key would both see no
existing version and both insert, forking the document's version history. A
transaction-scoped advisory lock keyed on the document key, taken before the
check, serializes them; it releases automatically at commit or rollback."""

from types import SimpleNamespace
from typing import Any, cast

from gg_ingestion.models import DocMeta
from gg_ingestion.registry import register_version
from sqlalchemy.ext.asyncio import AsyncSession


class _Result:
    def __init__(self, row: Any = None) -> None:
        self._row = row

    def one(self) -> Any:
        return self._row

    def first(self) -> Any:
        return self._row


class _RecordingSession:
    """Records every SQL text and returns preset results in call order."""

    def __init__(self, results: list[_Result]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, clause: object, params: dict[str, Any] | None = None) -> _Result:
        self.calls.append((str(clause), params))
        return self._results.pop(0)


def _new_version_session() -> _RecordingSession:
    # Order: advisory lock, INSERT documents (.one), SELECT version (.first=None),
    # INSERT version (.one).
    return _RecordingSession(
        [
            _Result(),  # advisory lock (result ignored)
            _Result(SimpleNamespace(id="doc-1")),  # documents upsert
            _Result(None),  # no existing version
            _Result(SimpleNamespace(id="ver-1")),  # version insert
        ]
    )


async def test_advisory_lock_is_taken_first_keyed_on_doc_key():
    session = _new_version_session()
    meta = DocMeta(doc_key="SOP-004", doc_type="sop", title="t", revision="A")

    registered = await register_version(
        cast(AsyncSession, session),
        meta=meta,
        content_hash="h",
        source_path="SOP-004.docx",
        size_bytes=1,
        object_key="documents/SOP-004.docx",
    )

    assert registered.created is True
    assert registered.version_id == "ver-1"
    # The very first statement is the advisory lock, before any document row is
    # touched, and it is keyed on this document's key.
    first_sql, first_params = session.calls[0]
    assert "pg_advisory_xact_lock" in first_sql
    assert first_params is not None
    assert first_params["doc_key"] == "SOP-004"
