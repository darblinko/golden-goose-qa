"""Source retirement logic with fake datastores (the full path over live
Postgres + Qdrant is covered by tests/integration/test_source_viewer.py)."""

from typing import cast

from gg_ingestion.retire import RetirementPlan, plan_retirements, retire_source_path
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession


class _Row:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class _Result:
    def __init__(self, rows=(), rowcount=0):
        self._rows = list(rows)
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, results, events):
        self._results = list(results)
        self._events = events
        self.statements = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if "DELETE FROM app.chunks" in sql:
            self._events.append("db:delete-chunks")
        elif "UPDATE app.documents SET deleted_at" in sql:
            self._events.append("db:tombstone")
        return self._results.pop(0)


class _FakeQdrant:
    def __init__(self, events):
        self._events = events
        self.deletes = []

    async def delete(self, *, collection_name, points_selector, wait):
        self._events.append("qdrant:delete")
        self.deletes.append(collection_name)


async def test_retire_tombstones_and_removes_projections():
    events: list[str] = []
    session = _FakeSession(
        [
            _Result([_Row(document_id="doc-1", doc_key="SOP-004")]),  # resolve
            _Result([_Row(id="v1"), _Row(id="v2")]),  # versions
            _Result(rowcount=3),  # delete chunks v1
            _Result(rowcount=2),  # delete chunks v2
            _Result(),  # tombstone update
        ],
        events,
    )
    qdrant = _FakeQdrant(events)

    result = await retire_source_path(
        cast(AsyncSession, session),
        cast(AsyncQdrantClient, qdrant),
        source_path="SOP-004.docx",
        collection="gg_chunks",
    )

    assert result is not None
    assert result.doc_key == "SOP-004"
    assert result.version_ids == ("v1", "v2")
    assert result.chunks_deleted == 5
    assert qdrant.deletes == ["gg_chunks"]
    # Vectors leave the index before any registry write, and the tombstone is
    # the final registry state change.
    assert events[0] == "qdrant:delete"
    assert events.index("qdrant:delete") < events.index("db:delete-chunks")
    assert events[-1] == "db:tombstone"


async def test_retire_is_idempotent_when_no_live_document():
    events: list[str] = []
    session = _FakeSession([_Result([])], events)  # resolve finds nothing
    qdrant = _FakeQdrant(events)

    result = await retire_source_path(
        cast(AsyncSession, session),
        cast(AsyncQdrantClient, qdrant),
        source_path="ALREADY-GONE.docx",
        collection="gg_chunks",
    )

    assert result is None
    assert qdrant.deletes == []  # nothing retired, nothing tombstoned
    assert events == []


def test_plan_retirements_retires_a_genuine_deletion():
    # The deleted path's doc_key did not reappear this cycle: a real removal.
    plan = plan_retirements({"a/SOP-1.docx": "SOP-1"}, reingested={})
    assert plan == RetirementPlan(retire=("a/SOP-1.docx",), rebind=())


def test_plan_retirements_treats_a_reappearing_doc_key_as_a_rename():
    # SOP-1 was deleted at the old path but re-ingested from a new path in the
    # same cycle — a source-side move, not a removal. Rebind, do not retire.
    plan = plan_retirements({"a/SOP-1.docx": "SOP-1"}, reingested={"SOP-1": "b/SOP-1.docx"})
    assert plan == RetirementPlan(retire=(), rebind=(("a/SOP-1.docx", "b/SOP-1.docx"),))


def test_plan_retirements_retires_when_no_live_binding():
    # Nothing live is bound to the deleted path (already tombstoned, or never
    # ingested); it falls to the idempotent retire path.
    plan = plan_retirements({"a/gone.docx": None}, reingested={"SOP-9": "x/keep.docx"})
    assert plan == RetirementPlan(retire=("a/gone.docx",), rebind=())


def test_plan_retirements_separates_a_mixed_batch():
    plan = plan_retirements(
        {
            "a/SOP-1.docx": "SOP-1",  # renamed to b/
            "a/SOP-2.docx": "SOP-2",  # genuinely deleted
            "a/orphan.docx": None,  # no live binding
        },
        reingested={"SOP-1": "b/SOP-1.docx", "SOP-3": "c/new.docx"},
    )
    assert plan.rebind == (("a/SOP-1.docx", "b/SOP-1.docx"),)
    assert set(plan.retire) == {"a/SOP-2.docx", "a/orphan.docx"}


def test_plan_retirements_skips_a_path_reingested_unchanged_in_place():
    # Defensive: a path reported both deleted and re-ingested at the *same* path
    # is live where it stands — neither retire nor rebind.
    plan = plan_retirements({"a/SOP-1.docx": "SOP-1"}, reingested={"SOP-1": "a/SOP-1.docx"})
    assert plan == RetirementPlan(retire=(), rebind=())
