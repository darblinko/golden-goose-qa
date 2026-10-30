"""A retired document that is ingested again is reindexed and its tombstone is
cleared; retirement removed its chunks and points, so it must not be reported
unchanged."""

from types import SimpleNamespace
from typing import Any, cast

from gg_ingestion import registry
from test_pipeline_drift_shortcircuit import _FakeSession, _pipeline, _route


def _registered(*, tombstoned: bool) -> registry.RegisteredVersion:
    return registry.RegisteredVersion(
        document_id="doc-1",
        version_id="ver-1",
        content_hash="h",
        doc_key="SOP-004",
        created=False,
        tombstoned=tombstoned,
    )


async def _short_circuit(registered: registry.RegisteredVersion) -> Any:
    # Retirement deleted the chunks and the points: 0 expected, 0 live.
    return await _pipeline(live_count=0)._registration_short_circuit(
        cast(Any, _FakeSession(child_count=0)),
        route=_route(),
        rel_path="a/sop.pdf",
        data=b"x",
        object_key="k",
        registered=registered,
    )


async def test_live_childless_version_still_short_circuits():
    result = await _short_circuit(_registered(tombstoned=False))
    assert result is not None and result.state == "unchanged"


async def test_retired_document_is_reindexed_instead_of_unchanged():
    assert await _short_circuit(_registered(tombstoned=True)) is None


class _RecordingSession:
    def __init__(self, cleared: bool) -> None:
        self._cleared = cleared
        self.statements: list[tuple[str, dict]] = []

    async def execute(self, clause: Any, params: Any = None) -> Any:
        sql = str(clause)
        self.statements.append((sql, params))
        row = SimpleNamespace(id="doc-1") if self._cleared else None
        return SimpleNamespace(first=lambda: row)


async def test_restore_clears_tombstone_and_requeues_other_versions():
    session = _RecordingSession(cleared=True)
    restored = await registry.restore_document(
        cast(Any, session), document_id="doc-1", version_id="ver-2"
    )
    assert restored is True
    clear_sql, clear_params = session.statements[0]
    assert "SET deleted_at = NULL" in clear_sql
    assert clear_params == {"document_id": "doc-1"}
    requeue_sql, requeue_params = session.statements[1]
    assert "pipeline_state = 'registered'" in requeue_sql
    assert requeue_params == {"document_id": "doc-1", "version_id": "ver-2"}


async def test_restore_is_a_no_op_for_a_live_document():
    session = _RecordingSession(cleared=False)
    restored = await registry.restore_document(
        cast(Any, session), document_id="doc-1", version_id="ver-2"
    )
    assert restored is False
    assert len(session.statements) == 1
