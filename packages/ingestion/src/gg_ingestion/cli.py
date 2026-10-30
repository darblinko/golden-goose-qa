"""Ingestion CLI.

    gg-ingest run --corpus data/synthetic/corpus
    gg-ingest status
    gg-ingest graph-migrate
    gg-ingest derive [--skip-graph]
    gg-ingest sync --source-root /mnt/qms-share --staging data/staging [--watch 30] [--ingest]

`run` walks the corpus, registers and indexes every file, and prints a state
summary. Exit code is nonzero when any document failed a parse or QA gate —
CI treats a silent ingestion failure as a build failure. `derive` rebuilds
the knowledge graph and register warehouse from the parsed artifacts of the
latest indexed versions; `graph-migrate` applies Cypher schema migrations.
`sync` mirrors a source connector into a staging corpus (the watch-folder
workflow) and can ingest each changed cycle with `--ingest`.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from gg_common.costs import track_costs
from gg_common.db import create_engine, create_session_factory
from gg_common.graphstore import graph_driver
from gg_common.logging import configure_logging
from gg_common.objectstore import LocalObjectStore, ObjectStore, S3ObjectStore
from gg_common.providers.factory import build_providers
from gg_common.settings import AppSettings, get_settings
from gg_common.tracing import configure_tracing, reset_tracing

from gg_ingestion import registry
from gg_ingestion.connectors import (
    FilesystemConnector,
    SyncReport,
    acknowledge_sync,
    sync_connector,
)
from gg_ingestion.extract.derive import DeriveReport, derive_corpus
from gg_ingestion.extract.graph_migrate import apply_migrations
from gg_ingestion.indexer import make_client
from gg_ingestion.pipeline import CorpusReport, IngestionPipeline, StageFailureRateError
from gg_ingestion.retire import RetiredSource, plan_retirements, retire_source_path

_DEFAULT_CYPHER_DIR = Path("infra/migrations/cypher")


def _object_store(settings: AppSettings, local_root: str | None) -> ObjectStore:
    if local_root:
        return LocalObjectStore(Path(local_root))
    store = S3ObjectStore(settings.objectstore)
    store.ensure_bucket(settings.objectstore.bucket_documents)
    store.ensure_bucket(settings.objectstore.bucket_artifacts)
    return store


async def _ingest_corpus(
    corpus: Path, local_store: str | None
) -> tuple[CorpusReport, StageFailureRateError | None]:
    """Ingest a corpus and print its report; the caller decides the exit code.
    Shared by the one-shot `run` command and each `sync --ingest` cycle so both
    surface the same per-document outcomes."""
    settings = get_settings()
    providers = build_providers(settings.providers)
    engine = create_engine(settings.postgres)
    qdrant = make_client(settings.qdrant)
    gate_error: StageFailureRateError | None = None
    with track_costs() as costs:
        try:
            pipeline = IngestionPipeline(
                settings=settings,
                session_factory=create_session_factory(engine),
                qdrant=qdrant,
                object_store=_object_store(settings, local_store),
                embeddings=providers.embeddings,
                ocr=providers.ocr,
            )
            try:
                report = await pipeline.ingest_corpus(corpus)
            except StageFailureRateError as exc:
                # A systemic failure rate still produced a full report; surface
                # every per-document outcome, then fail the run loudly.
                report, gate_error = exc.report, exc
        finally:
            await qdrant.close()
            await engine.dispose()
    _print_report(report, using_fakes=providers.using_fakes, usage=costs.summary())
    if gate_error is not None:
        print(f"GATE {gate_error}", file=sys.stderr)
    return report, gate_error


async def _run(corpus: Path, local_store: str | None) -> int:
    report, gate_error = await _ingest_corpus(corpus, local_store)
    return 1 if (report.failed or gate_error is not None) else 0


def _print_report(
    report: CorpusReport, *, using_fakes: tuple[str, ...], usage: dict[str, Any]
) -> None:
    counts = report.counts()
    total = len(report.results)
    print(f"ingested {total} files: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    _print_usage(usage)
    if using_fakes:
        print(f"NOTE: fake providers in use for: {', '.join(using_fakes)}")
    for result in report.failed:
        print(f"FAILED {result.path}: {result.reason}", file=sys.stderr)


def _print_usage(usage: dict[str, Any]) -> None:
    print(
        f"provider usage: input_tokens={usage['input_tokens']} "
        f"output_tokens={usage['output_tokens']} est_cost_usd={usage['cost_usd']}"
    )
    for stage, stats in sorted(usage["by_stage"].items()):
        print(
            f"  {stage}: input_tokens={stats['input_tokens']} "
            f"output_tokens={stats['output_tokens']} est_cost_usd={stats['cost_usd']}"
        )


async def _derive(local_store: str | None, skip_graph: bool) -> int:
    settings = get_settings()
    engine = create_engine(settings.postgres)
    try:
        factory = create_session_factory(engine)
        store = _object_store(settings, local_store)
        if skip_graph:
            report = await derive_corpus(
                settings=settings, session_factory=factory, object_store=store, graph=None
            )
        else:
            async with graph_driver(settings.neo4j) as driver:
                report = await derive_corpus(
                    settings=settings, session_factory=factory, object_store=store, graph=driver
                )
    finally:
        await engine.dispose()
    _print_derive_report(report)
    return 0


def _print_derive_report(report: DeriveReport) -> None:
    graph_note = "graph loaded" if report.graph_loaded else "graph skipped"
    print(
        f"derived {report.documents} documents: {report.nodes} node assertions, "
        f"{report.edges} edge assertions (the graph load merges duplicates by key), "
        f"{report.register_rows} register rows ({graph_note})"
    )
    for doc_key, refs in sorted(report.dangling_refs.items()):
        print(f"dangling refs in {doc_key}: {', '.join(refs)}")
    for warning in report.warnings:
        print(f"WARNING {warning}", file=sys.stderr)


async def _sync(
    source_root: Path,
    staging: Path,
    *,
    watch: float | None,
    ingest: bool,
    local_store: str | None,
) -> int:
    connector = FilesystemConnector(source_root)
    while True:
        # With --ingest the manifest only advances for changes that ingestion,
        # retirement and derivation completed; anything else is offered again
        # by the next sync instead of being treated as already processed.
        report = await sync_connector(connector, staging, acknowledge=not ingest)
        _print_sync_report(connector.name, report)
        ok = True
        if ingest and (report.fetched or report.deleted):
            ok = await _process_sync_changes(report, staging, local_store)
        if watch is None:
            return 0 if ok else 1
        await asyncio.sleep(watch)


async def _process_sync_changes(report: SyncReport, staging: Path, local_store: str | None) -> bool:
    """Ingest, retire and derive one sync cycle's changes, then acknowledge the
    ones that completed. Returns False when any fetched document failed."""
    corpus_report: CorpusReport | None = None
    gate_error: StageFailureRateError | None = None
    if report.fetched:
        corpus_report, gate_error = await _ingest_corpus(staging, local_store)
    if report.deleted:
        # A source that disappeared from the listing is retired from the
        # index and tombstoned, unless the same cycle re-ingested its doc_key
        # under a new path, which is a rename: rebind, do not retire
        # (retiring would destroy a just-re-confirmed document).
        _print_retired(await _reconcile_deletions(report.deleted, corpus_report))
    # Adds, updates, and retirements only reach retrieval once the graph and
    # register warehouse are rebuilt; do it now instead of leaving them stale
    # until a manual derive.
    await _derive(local_store, skip_graph=False)
    completed = _completed_fetches(report.fetched, corpus_report)
    acknowledge_sync(report, fetched=completed, deleted=report.deleted)
    return gate_error is None and len(completed) == len(report.fetched)


def _completed_fetches(fetched: tuple[str, ...], report: CorpusReport | None) -> list[str]:
    """Fetched source ids whose ingestion reached a terminal non-failure state."""
    if report is None:
        return []
    done = {r.path for r in report.results if r.state != "failed"}
    return [source_id for source_id in fetched if source_id in done]


def _reingested_paths(report: CorpusReport | None) -> dict[str, str]:
    """doc_key -> source path for every document this cycle left live (freshly
    indexed or idempotently unchanged). A deleted path whose doc_key appears here
    under a different path is a rename rather than a removal."""
    if report is None:
        return {}
    live = {"indexed", "unchanged"}
    return {r.doc_key: r.path for r in report.results if r.state in live}


async def _reconcile_deletions(
    deleted: tuple[str, ...], corpus_report: CorpusReport | None
) -> list[RetiredSource]:
    reingested = _reingested_paths(corpus_report)
    settings = get_settings()
    engine = create_engine(settings.postgres)
    qdrant = make_client(settings.qdrant)
    retired: list[RetiredSource] = []
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            bindings = await registry.resolve_doc_keys_by_source_paths(session, deleted)
        plan = plan_retirements({src: bindings.get(src) for src in deleted}, reingested)
        for old_path, new_path in plan.rebind:
            async with factory() as session:
                await registry.rebind_source_path(
                    session, old_source_path=old_path, new_source_path=new_path
                )
                await session.commit()
            print(f"  rebound {old_path} -> {new_path}")
        for source_id in plan.retire:
            async with factory() as session:
                result = await retire_source_path(
                    session,
                    qdrant,
                    source_path=source_id,
                    collection=settings.qdrant.collection,
                )
                await session.commit()
            if result is not None:
                retired.append(result)
    finally:
        await qdrant.close()
        await engine.dispose()
    return retired


def _print_retired(retired: list[RetiredSource]) -> None:
    for source in retired:
        print(
            f"  retired {source.doc_key} "
            f"({len(source.version_ids)} versions, {source.chunks_deleted} chunks)"
        )


def _print_sync_report(source: str, report: SyncReport) -> None:
    print(
        f"sync [{source}]: fetched={len(report.fetched)} "
        f"unchanged={len(report.unchanged)} deleted={len(report.deleted)}"
    )
    for source_id in report.fetched:
        print(f"  fetched {source_id}")
    for source_id in report.deleted:
        print(f"  deleted {source_id}")


async def _graph_migrate(migrations_dir: Path) -> int:
    settings = get_settings()
    async with graph_driver(settings.neo4j) as driver:
        applied = await apply_migrations(driver, migrations_dir)
    if applied:
        print("applied cypher migrations: " + ", ".join(applied))
    else:
        print("cypher schema up to date")
    return 0


async def _status() -> int:
    settings = get_settings()
    engine = create_engine(settings.postgres)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            summary = await registry.pipeline_summary(session)
    finally:
        await engine.dispose()
    if not summary:
        print("registry is empty")
        return 0
    for state, count in summary.items():
        print(f"{state}: {count}")
    return 0


def main() -> int:
    settings = get_settings()
    configure_logging(settings)
    configure_tracing(settings.tracing)
    parser = argparse.ArgumentParser(prog="gg-ingest")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="ingest a corpus directory")
    run.add_argument("--corpus", type=Path, required=True)
    run.add_argument(
        "--local-store",
        default=None,
        help="use a filesystem object store rooted here instead of S3/SeaweedFS",
    )
    sub.add_parser("status", help="registry pipeline-state summary")

    derive = sub.add_parser("derive", help="derive graph + registers from parsed artifacts")
    derive.add_argument(
        "--local-store",
        default=None,
        help="use a filesystem object store rooted here instead of S3/SeaweedFS",
    )
    derive.add_argument(
        "--skip-graph", action="store_true", help="load only the register warehouse"
    )

    migrate = sub.add_parser("graph-migrate", help="apply Cypher schema migrations")
    migrate.add_argument("--migrations", type=Path, default=_DEFAULT_CYPHER_DIR)

    sync = sub.add_parser("sync", help="mirror a source connector into a staging corpus")
    sync.add_argument("--source-root", type=Path, required=True, help="directory to watch")
    sync.add_argument("--staging", type=Path, required=True, help="staging corpus directory")
    sync.add_argument(
        "--watch",
        type=float,
        default=None,
        metavar="SECONDS",
        help="poll continuously at this interval instead of a one-shot sync",
    )
    sync.add_argument(
        "--ingest", action="store_true", help="ingest the staging corpus after each changed cycle"
    )
    sync.add_argument(
        "--local-store",
        default=None,
        help="use a filesystem object store rooted here instead of S3/SeaweedFS",
    )

    args = parser.parse_args()
    try:
        if args.command == "run":
            if not args.corpus.is_dir():
                print(f"corpus directory not found: {args.corpus}", file=sys.stderr)
                return 2
            return asyncio.run(_run(args.corpus, args.local_store))
        if args.command == "derive":
            return asyncio.run(_derive(args.local_store, args.skip_graph))
        if args.command == "graph-migrate":
            return asyncio.run(_graph_migrate(args.migrations))
        if args.command == "sync":
            if not args.source_root.is_dir():
                print(f"source root not found: {args.source_root}", file=sys.stderr)
                return 2
            return asyncio.run(
                _sync(
                    args.source_root,
                    args.staging,
                    watch=args.watch,
                    ingest=args.ingest,
                    local_store=args.local_store,
                )
            )
        return asyncio.run(_status())
    finally:
        reset_tracing()


if __name__ == "__main__":
    raise SystemExit(main())
