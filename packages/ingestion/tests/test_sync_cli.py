"""`sync --ingest` acknowledges only the changes downstream processing completed."""

import os
from datetime import UTC, datetime

from gg_ingestion import cli
from gg_ingestion.pipeline import CorpusReport, IngestResult

_T1 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC).timestamp()


def _write(root, source_id, content):
    path = root / source_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (_T1, _T1))


def _stub_downstream(monkeypatch, failing: set[str], calls: dict[str, list]):
    async def ingest(staging, local_store):
        results = tuple(
            IngestResult(
                path=str(p.relative_to(staging)),
                doc_key=p.stem,
                state="failed" if str(p.relative_to(staging)) in failing else "indexed",
            )
            for p in sorted(staging.rglob("*"))
            if p.is_file()
        )
        calls["ingest"].append([r.path for r in results])
        return CorpusReport(results=results), None

    async def reconcile(deleted, corpus_report):
        calls["retire"].append(list(deleted))
        return []

    async def derive(local_store, skip_graph):
        calls["derive"].append(skip_graph)
        return 0

    monkeypatch.setattr(cli, "_ingest_corpus", ingest)
    monkeypatch.setattr(cli, "_reconcile_deletions", reconcile)
    monkeypatch.setattr(cli, "_derive", derive)


async def test_failed_ingestion_is_retried_and_deletion_still_retired(monkeypatch, tmp_path):
    source, staging = tmp_path / "source", tmp_path / "staging"
    _write(source, "a.docx", b"a")
    _write(source, "old.docx", b"old")
    calls: dict[str, list] = {"ingest": [], "retire": [], "derive": []}
    _stub_downstream(monkeypatch, failing=set(), calls=calls)
    assert await cli._sync(source, staging, watch=None, ingest=True, local_store=None) == 0

    (source / "old.docx").unlink()
    _write(source, "new.docx", b"new")
    _stub_downstream(monkeypatch, failing={"new.docx"}, calls=calls)
    assert await cli._sync(source, staging, watch=None, ingest=True, local_store=None) == 1
    # The deletion seen alongside the failed addition was retired and derived.
    assert calls["retire"] == [["old.docx"]]
    assert len(calls["derive"]) == 2

    _stub_downstream(monkeypatch, failing=set(), calls=calls)
    assert await cli._sync(source, staging, watch=None, ingest=True, local_store=None) == 0
    # The failed addition is offered again; the acknowledged deletion is not.
    assert calls["ingest"][-1] == ["a.docx", "new.docx"]
    assert calls["retire"] == [["old.docx"]]

    calls["ingest"].clear()
    assert await cli._sync(source, staging, watch=None, ingest=True, local_store=None) == 0
    assert calls["ingest"] == []
