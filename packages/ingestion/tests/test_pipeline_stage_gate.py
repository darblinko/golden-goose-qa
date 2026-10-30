"""Stage failures are recorded, not vanished, and a systemic failure rate aborts
the corpus run.

Two properties the registry-wide contract depends on (architecture §6.3, "errors
are data"): an unexpected stage crash (a provider outage mid-embed/index) leaves
the document queryable as `failed` rather than rolling its registration away, and
a corpus whose *attempted* documents fail above the tolerated fraction fails the
whole run loudly instead of reporting partial success.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from gg_ingestion import indexer, registry
from gg_ingestion.models import DocMeta
from gg_ingestion.parsers.base import DocumentParser, ParseError
from gg_ingestion.parsers.router import Route
from gg_ingestion.pipeline import (
    CorpusReport,
    IngestionPipeline,
    IngestResult,
    StageFailureRateError,
)


def _result(state: str, *, stage_attempted: bool) -> IngestResult:
    return IngestResult(
        path=f"{state}.pdf", doc_key=state, state=cast(Any, state), stage_attempted=stage_attempted
    )


class TestCorpusReportAccounting:
    def test_rate_counts_only_attempted_documents(self):
        report = CorpusReport(
            results=(
                _result("indexed", stage_attempted=True),
                _result("failed", stage_attempted=True),  # a stage failure
                _result("failed", stage_attempted=False),  # a routing failure, not a stage
                _result("skipped_unsupported", stage_attempted=False),
                _result("unchanged", stage_attempted=False),
            )
        )
        assert report.stage_attempts == 2
        assert report.stage_failures == 1
        assert report.stage_failure_rate == 0.5

    def test_no_attempts_is_not_a_breach(self):
        report = CorpusReport(
            results=(
                _result("skipped_unsupported", stage_attempted=False),
                _result("unchanged", stage_attempted=False),
            )
        )
        assert report.stage_failure_rate == 0.0
        assert not report.stage_failure_gate_breached(0.10)

    def test_gate_uses_strict_greater_than(self):
        # Exactly at the threshold is tolerated; above it is a breach.
        at_threshold = CorpusReport(
            results=tuple(
                _result("failed" if i == 0 else "indexed", stage_attempted=True) for i in range(10)
            )
        )
        assert at_threshold.stage_failure_rate == 0.10
        assert not at_threshold.stage_failure_gate_breached(0.10)

        over_threshold = CorpusReport(
            results=tuple(
                _result("failed" if i < 2 else "indexed", stage_attempted=True) for i in range(10)
            )
        )
        assert over_threshold.stage_failure_rate == 0.20
        assert over_threshold.stage_failure_gate_breached(0.10)


class _RaisingParser(DocumentParser):
    """A stage crash that is not a ParseError — an unexpected provider/index
    outage rather than an unparseable document."""

    name = "raising"

    def parse(self, path: Path, meta: DocMeta) -> Any:
        raise RuntimeError("embedding provider outage")


class _FakeSession:
    def __init__(self, events: list[str], label: str) -> None:
        self._events = events
        self._label = label

    async def __aenter__(self) -> "_FakeSession":
        self._events.append(f"{self._label}:open")
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def commit(self) -> None:
        self._events.append(f"{self._label}:commit")

    async def rollback(self) -> None:
        self._events.append(f"{self._label}:rollback")

    async def execute(self, clause: object, *args: object, **kwargs: object) -> Any:
        if "pg_advisory_xact_lock" in str(clause):
            return None  # the processing transaction takes the document lock first
        raise AssertionError("no SQL expected on the stage-failure path")


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.events: list[str] = []
        self._n = 0

    def __call__(self) -> _FakeSession:
        self._n += 1
        return _FakeSession(self.events, f"s{self._n}")


def _stage_failure_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[IngestionPipeline, list[tuple]]:
    factory = _FakeSessionFactory()
    settings = SimpleNamespace(objectstore=SimpleNamespace(bucket_documents="documents"))
    store = SimpleNamespace(exists=lambda bucket, key: True, put=lambda *a: None)
    pipeline = IngestionPipeline(
        settings=cast(Any, settings),
        session_factory=cast(Any, factory),
        qdrant=cast(Any, None),
        object_store=cast(Any, store),
        embeddings=cast(Any, SimpleNamespace(dimensions=8)),
        ocr=cast(Any, None),
    )
    route = Route(
        meta=DocMeta(doc_key="SOP-001", doc_type="sop", title="t", file_format="pdf"),
        parser=_RaisingParser(),
    )
    monkeypatch.setattr(pipeline.router, "route", lambda path: route)

    async def fake_register(session: object, **kwargs: Any) -> registry.RegisteredVersion:
        return registry.RegisteredVersion(
            document_id="doc-1",
            version_id="ver-1",
            content_hash=kwargs["content_hash"],
            doc_key=kwargs["meta"].doc_key,
            created=True,
        )

    updates: list[tuple] = []

    async def fake_update(session: object, version_id: str, **kwargs: Any) -> None:
        updates.append((version_id, kwargs.get("pipeline_state"), kwargs.get("failure_reason")))

    monkeypatch.setattr(registry, "register_version", fake_register)
    monkeypatch.setattr(registry, "update_version", fake_update)
    return pipeline, updates


async def test_unexpected_stage_crash_records_failed_and_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pipeline, updates = _stage_failure_pipeline(monkeypatch)
    doc = tmp_path / "sop.pdf"
    doc.write_bytes(b"%PDF-1.4 fake")

    result = await pipeline.ingest_file(doc, corpus_root=tmp_path)

    assert result.state == "failed"
    assert result.stage_attempted is True
    assert "embedding provider outage" in (result.reason or "")
    # The failed state is persisted, so the document stays queryable as failed.
    assert updates == [("ver-1", "failed", "stage error: embedding provider outage")]


async def test_registration_commits_before_stages_and_failure_is_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pipeline, _ = _stage_failure_pipeline(monkeypatch)
    factory = cast(_FakeSessionFactory, pipeline.session_factory)
    doc = tmp_path / "sop.pdf"
    doc.write_bytes(b"%PDF-1.4 fake")

    await pipeline.ingest_file(doc, corpus_root=tmp_path)

    # Registration (s1) commits first; the stage transaction (s2) rolls back on
    # the crash; the failed state is written in a third, independent transaction.
    assert factory.events == [
        "s1:open",
        "s1:commit",
        "s2:open",
        "s2:rollback",
        "s3:open",
        "s3:commit",
    ]


async def _noop_ensure_collection(*args: object, **kwargs: object) -> None:
    return None


def _gate_pipeline() -> IngestionPipeline:
    return IngestionPipeline(
        settings=cast(Any, SimpleNamespace(qdrant=None)),
        session_factory=cast(Any, None),
        qdrant=cast(Any, None),
        object_store=cast(Any, None),
        embeddings=cast(Any, SimpleNamespace(dimensions=8)),
        ocr=cast(Any, None),
    )


def _write_corpus(root: Path, n: int) -> None:
    for i in range(n):
        (root / f"f{i}.txt").write_text("x")


async def test_ingest_corpus_raises_when_stage_failures_exceed_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(indexer, "ensure_collection", _noop_ensure_collection)
    _write_corpus(tmp_path, 10)
    pipeline = _gate_pipeline()

    async def fake_ingest(path: Path, *, corpus_root: Path) -> IngestResult:
        idx = int(path.stem[1:])
        state = "failed" if idx < 2 else "indexed"  # 2/10 = 20% > 10%
        return IngestResult(
            path=path.name, doc_key=path.stem, state=cast(Any, state), stage_attempted=True
        )

    monkeypatch.setattr(pipeline, "ingest_file", fake_ingest)

    with pytest.raises(StageFailureRateError) as caught:
        await pipeline.ingest_corpus(tmp_path)
    # The report is carried on the error so callers can still surface outcomes.
    assert caught.value.report.stage_failures == 2
    assert caught.value.report.stage_attempts == 10


async def test_ingest_corpus_returns_report_at_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(indexer, "ensure_collection", _noop_ensure_collection)
    _write_corpus(tmp_path, 10)
    pipeline = _gate_pipeline()

    async def fake_ingest(path: Path, *, corpus_root: Path) -> IngestResult:
        idx = int(path.stem[1:])
        state = "failed" if idx == 0 else "indexed"  # 1/10 = 10%, not over the gate
        return IngestResult(
            path=path.name, doc_key=path.stem, state=cast(Any, state), stage_attempted=True
        )

    monkeypatch.setattr(pipeline, "ingest_file", fake_ingest)

    report = await pipeline.ingest_corpus(tmp_path)
    assert report.stage_failure_rate == 0.10
    assert len(report.failed) == 1


def test_parse_error_is_a_runtime_error_subclass_but_not_caught_as_unexpected():
    # Guards the test's premise: a plain RuntimeError from a stage is *not* a
    # ParseError, so it takes the unexpected-crash path, not the parse-failed one.
    assert issubclass(ParseError, RuntimeError)
    assert not isinstance(RuntimeError("x"), ParseError)
