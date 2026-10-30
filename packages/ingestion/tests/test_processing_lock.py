"""Processing holds the per-document ingest lock for its whole transaction.
Registration takes the lock and commits, which releases it. Without the lock
in the processing transaction, two ingests of different bytes carrying the
same revision both pass assert_unique_revision before either commits."""

from types import SimpleNamespace
from typing import Any, cast

from gg_ingestion.pipeline import IngestionPipeline, _Registration


class _Session:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, clause: Any, params: Any = None) -> None:
        if "pg_advisory_xact_lock" in str(clause):
            self.log.append(f"lock {params['doc_key']}")

    async def commit(self) -> None:
        self.log.append("commit")

    async def rollback(self) -> None:
        self.log.append("rollback")


async def test_processing_takes_the_document_lock_before_any_stage():
    log: list[str] = []
    pipeline = IngestionPipeline(
        settings=cast(Any, SimpleNamespace()),
        session_factory=cast(Any, lambda: _Session(log)),
        qdrant=cast(Any, None),
        object_store=cast(Any, None),
        embeddings=cast(Any, SimpleNamespace(dimensions=8)),
        ocr=cast(Any, None),
    )

    async def _stages(session: Any, **_: Any) -> str:
        log.append("stages")
        return "result"

    pipeline._process_stages = _stages  # type: ignore[method-assign,assignment]
    registration = _Registration(
        document_id="doc-1", version_id="ver-1", doc_key="SOP-004", short_circuit=None
    )
    result = await pipeline._run_stages(
        route=cast(Any, None),
        path=cast(Any, None),
        rel_path="a/sop.docx",
        content_hash="h",
        registration=registration,
        started=0.0,
    )
    assert result == "result"
    assert log == ["lock SOP-004", "stages", "commit"]
