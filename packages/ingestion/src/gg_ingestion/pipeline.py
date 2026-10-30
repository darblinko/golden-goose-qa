"""Staged ingestion pipeline: register → parse → chunk → index.

Stage outputs (parse.json, chunks.json, metrics.json) are written to the
artifacts bucket keyed by content hash, so any stage can be inspected or
re-run against the exact bytes it saw. Content-hash idempotency means
re-ingesting an unchanged corpus is a no-op; a failed document is retried on
the next run.
"""

import hashlib
import json
import time
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Literal

from gg_common.audit import AuditEvent, write_audit_event
from gg_common.drift import classify_drift
from gg_common.objectstore import ObjectStore
from gg_common.providers.base import EmbeddingProvider, OCRProvider
from gg_common.settings import AppSettings
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gg_ingestion import indexer, registry
from gg_ingestion.artifacts import artifact_key
from gg_ingestion.chunking import chunk_document
from gg_ingestion.controlled import enforce_controlled_metadata
from gg_ingestion.docmeta import UnrecognizedDocumentError
from gg_ingestion.extract.records import RecordExtractionError, record_event_date
from gg_ingestion.metrics import IngestGateError, compute_metrics, enforce_gates
from gg_ingestion.models import DocMeta, ParsedDocument
from gg_ingestion.parsers.base import (
    AsyncDocumentParser,
    DocumentParser,
    NoTextLayerError,
    ParseError,
)
from gg_ingestion.parsers.pdf_form import PdfFormParser
from gg_ingestion.parsers.router import ParserRouter, Route
from gg_ingestion.processing_config import processing_config_hash

ResultState = Literal["indexed", "unchanged", "skipped_unsupported", "failed"]

_AUDIT_ACTOR = "ingestion-pipeline"

# A corpus run tolerates a few individually-bad documents (each queryable as
# failed), but a failure rate above this fraction of *attempted* documents is a
# systemic breakdown — a provider outage or misconfiguration — and aborts the
# run loudly (architecture §6.3 "hard gates abort and surface").
_MAX_STAGE_FAILURE_RATE = 0.10


def _require_full_pdf_coverage(parsed: ParsedDocument) -> ParsedDocument:
    """A PDF parse must yield a block for every physical page. A page dropped
    below the born-digital text threshold with no embedded image, or an imageless
    page on the OCR path, would otherwise vanish while coverage metrics — measured
    only against the blocks that survived — still report 100%. The parsers record
    pdf_pages so this final check can fail loudly on any unrecovered page rather
    than index a document that is silently missing evidence."""
    total = parsed.attributes.get("pdf_pages")
    if total is None:
        return parsed
    covered = {block.page for block in parsed.blocks if block.page is not None}
    missing = [n for n in range(1, int(total) + 1) if n not in covered]
    if missing:
        raise ParseError(
            f"pdf {parsed.meta.doc_key} left page(s) {missing} unrecovered "
            f"(no text layer and no OCR-readable image); refusing partial coverage"
        )
    return parsed


@dataclass(frozen=True)
class IngestResult:
    path: str
    doc_key: str
    state: ResultState
    reason: str | None = None
    n_chunks: int = 0
    # True once a document entered staged processing (parse→chunk→index). Routing
    # failures, idempotent no-ops, and unsupported skips never attempt a stage,
    # so they are excluded from the corpus stage-failure rate.
    stage_attempted: bool = False


@dataclass(frozen=True)
class CorpusReport:
    results: tuple[IngestResult, ...]

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.state] = counts.get(result.state, 0) + 1
        return counts

    @property
    def failed(self) -> tuple[IngestResult, ...]:
        return tuple(r for r in self.results if r.state == "failed")

    @property
    def stage_attempts(self) -> int:
        return sum(1 for r in self.results if r.stage_attempted)

    @property
    def stage_failures(self) -> int:
        return sum(1 for r in self.results if r.stage_attempted and r.state == "failed")

    @property
    def stage_failure_rate(self) -> float:
        return self.stage_failures / self.stage_attempts if self.stage_attempts else 0.0

    def stage_failure_gate_breached(self, threshold: float) -> bool:
        return self.stage_attempts > 0 and self.stage_failure_rate > threshold


class StageFailureRateError(RuntimeError):
    """More than the tolerated fraction of attempted documents failed a pipeline
    stage. Carries the report so callers can still surface every per-document
    outcome — the corpus is measured, then the run is failed."""

    def __init__(self, report: CorpusReport, threshold: float) -> None:
        self.report = report
        self.threshold = threshold
        super().__init__(
            f"stage failure rate {report.stage_failure_rate:.0%} exceeds "
            f"{threshold:.0%} gate: {report.stage_failures}/{report.stage_attempts} "
            "attempted documents failed a pipeline stage"
        )


def version_effective_from(parsed: ParsedDocument) -> date | None:
    """A controlled document's effective date, else a record's own event date."""
    controlled = registry.parse_effective_date(parsed.attributes.get("effective_date"))
    return controlled or record_event_date(parsed)


@dataclass(frozen=True)
class _Registration:
    """Outcome of the committed registration phase. A non-None short_circuit is a
    terminal result (unchanged / skipped) with no stages left to run."""

    document_id: str
    version_id: str
    doc_key: str
    short_circuit: IngestResult | None
    tombstoned: bool = False


class IngestionPipeline:
    def __init__(
        self,
        *,
        settings: AppSettings,
        session_factory: async_sessionmaker[AsyncSession],
        qdrant: AsyncQdrantClient,
        object_store: ObjectStore,
        embeddings: EmbeddingProvider,
        ocr: OCRProvider,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.qdrant = qdrant
        self.object_store = object_store
        self.embeddings = embeddings
        self.router = ParserRouter(ocr=ocr)

    async def ingest_corpus(self, corpus_dir: Path) -> CorpusReport:
        await indexer.ensure_collection(
            self.qdrant,
            self.settings.qdrant,
            dimensions=self.embeddings.dimensions,
        )
        files = sorted(p for p in corpus_dir.rglob("*") if p.is_file())
        results = [await self.ingest_file(path, corpus_root=corpus_dir) for path in files]
        report = CorpusReport(results=tuple(results))
        if report.stage_failure_gate_breached(_MAX_STAGE_FAILURE_RATE):
            raise StageFailureRateError(report, _MAX_STAGE_FAILURE_RATE)
        return report

    async def ingest_file(self, path: Path, *, corpus_root: Path) -> IngestResult:
        started = time.monotonic()
        rel_path = str(path.relative_to(corpus_root)) if corpus_root in path.parents else str(path)

        try:
            route = self.router.route(path)
        except UnrecognizedDocumentError as exc:
            return IngestResult(path=rel_path, doc_key=path.stem, state="failed", reason=str(exc))

        data = path.read_bytes()
        content_hash = hashlib.sha256(data).hexdigest()
        object_key = f"{route.meta.doc_key}/{content_hash}/{path.name}"

        # Phase 1: register the version and store its bytes, committed before any
        # risky stage runs. A later stage crash then leaves a queryable failed
        # row instead of erasing the document from the registry entirely.
        registration = await self._register(
            route=route,
            rel_path=rel_path,
            data=data,
            content_hash=content_hash,
            object_key=object_key,
        )
        if registration.short_circuit is not None:
            return registration.short_circuit

        # Phase 2: staged processing in its own transaction. Expected failures
        # (parse, QA gate) are recorded as failed inside and committed. An
        # unexpected stage crash — a provider outage mid-embed/index — is caught
        # here, the version marked failed in an independent transaction, and the
        # result returned rather than raised, so one blip cannot abort the run.
        try:
            return await self._run_stages(
                route=route,
                path=path,
                rel_path=rel_path,
                content_hash=content_hash,
                registration=registration,
                started=started,
            )
        except Exception as exc:
            await self._mark_stage_failure(registration.version_id, exc)
            return IngestResult(
                path=rel_path,
                doc_key=registration.doc_key,
                state="failed",
                reason=f"stage error: {exc}",
                stage_attempted=True,
            )

    async def _register(
        self,
        *,
        route: Route,
        rel_path: str,
        data: bytes,
        content_hash: str,
        object_key: str,
    ) -> _Registration:
        async with self.session_factory() as session:
            try:
                registered = await registry.register_version(
                    session,
                    meta=route.meta,
                    content_hash=content_hash,
                    source_path=rel_path,
                    size_bytes=len(data),
                    object_key=object_key,
                )
                short_circuit = await self._registration_short_circuit(
                    session,
                    route=route,
                    rel_path=rel_path,
                    data=data,
                    object_key=object_key,
                    registered=registered,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return _Registration(
            document_id=registered.document_id,
            version_id=registered.version_id,
            doc_key=registered.doc_key,
            short_circuit=short_circuit,
            tombstoned=registered.tombstoned,
        )

    async def _registration_short_circuit(
        self,
        session: AsyncSession,
        *,
        route: Route,
        rel_path: str,
        data: bytes,
        object_key: str,
        registered: registry.RegisteredVersion,
    ) -> IngestResult | None:
        # A retired document never short-circuits: retirement removed its chunks
        # and points, so 0 == 0 would read as in sync. Reindex it to restore it.
        if not registered.created and not registered.tombstoned:
            state = await self._version_state(session, registered.version_id)
            if (
                state == "indexed"
                and await self._processing_config_matches(session, registered.version_id)
                and await self._indexed_points_in_sync(session, registered.version_id)
            ):
                return IngestResult(
                    path=rel_path,
                    doc_key=registered.doc_key,
                    state="unchanged",
                    reason="content hash already ingested",
                )
            # An 'indexed' version must NOT short-circuit as unchanged when its
            # Qdrant points have drifted (a delete that outran its upsert, a
            # repaired collection) or when it was indexed under a processing
            # configuration that has since changed (chunk sizes, embedding model) —
            # idempotency would otherwise leave it stale forever. Fall through to
            # re-run the stages and rebuild its chunks and points.
            # A previously deferred document is reprocessed once the router
            # gains a parser for it; while it still has none, stay skipped.
            if state == "skipped_unsupported" and route.parser is None:
                return IngestResult(
                    path=rel_path,
                    doc_key=registered.doc_key,
                    state="skipped_unsupported",
                    reason="content hash already ingested",
                )

        if not self.object_store.exists(self.settings.objectstore.bucket_documents, object_key):
            self.object_store.put(self.settings.objectstore.bucket_documents, object_key, data)

        if route.parser is None:
            await registry.update_version(
                session,
                registered.version_id,
                pipeline_state="skipped_unsupported",
                failure_reason=route.skip_reason,
            )
            return IngestResult(
                path=rel_path,
                doc_key=registered.doc_key,
                state="skipped_unsupported",
                reason=route.skip_reason,
            )
        return None

    async def _mark_stage_failure(self, version_id: str, exc: Exception) -> None:
        """Persist a stage crash as a failed version in its own transaction. The
        processing transaction was rolled back, so this independent write is what
        keeps the document queryable as failed — 'errors are data': a provider
        outage becomes an honest failed row, never a vanished document."""
        async with self.session_factory() as session:
            try:
                await registry.update_version(
                    session,
                    version_id,
                    pipeline_state="failed",
                    failure_reason=f"stage error: {exc}",
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _run_stages(
        self,
        *,
        route: Route,
        path: Path,
        rel_path: str,
        content_hash: str,
        registration: _Registration,
        started: float,
    ) -> IngestResult:
        async with self.session_factory() as session:
            try:
                result = await self._process_stages(
                    session,
                    route=route,
                    path=path,
                    rel_path=rel_path,
                    content_hash=content_hash,
                    registration=registration,
                    started=started,
                )
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    async def _process_stages(
        self,
        session: AsyncSession,
        *,
        route: Route,
        path: Path,
        rel_path: str,
        content_hash: str,
        registration: _Registration,
        started: float,
    ) -> IngestResult:
        assert route.parser is not None  # registration short-circuits the parser-less path
        try:
            parsed = await self._parse(route.parser, path, route.meta)
        except ParseError as exc:
            await registry.update_version(
                session,
                registration.version_id,
                pipeline_state="failed",
                failure_reason=str(exc),
            )
            return IngestResult(
                path=rel_path,
                doc_key=registration.doc_key,
                state="failed",
                reason=str(exc),
                stage_attempted=True,
            )

        parsed, sanitize_hits = _sanitize_document(parsed)
        self._put_artifact(
            registration.doc_key, content_hash, "parse.json", _parsed_to_json(parsed)
        )

        # A controlled document with no well-formed revision/effective date, or an
        # internal document number that disagrees with its filename identity, is
        # quarantined as failed before any chunking or indexing — never published
        # as evidence whose revision cannot be pinned to a date.
        try:
            enforce_controlled_metadata(parsed.meta, parsed.attributes)
            effective_from = version_effective_from(parsed)
        except (IngestGateError, RecordExtractionError) as exc:
            await registry.update_version(
                session,
                registration.version_id,
                pipeline_state="failed",
                failure_reason=str(exc),
            )
            return IngestResult(
                path=rel_path,
                doc_key=registration.doc_key,
                state="failed",
                reason=str(exc),
                stage_attempted=True,
            )

        await registry.update_version(
            session,
            registration.version_id,
            pipeline_state="parsed",
            revision=parsed.meta.revision,
            effective_from=effective_from,
        )

        # The authoritative revision is now known. Refuse a second version that
        # reuses another version's revision before any chunking/indexing runs —
        # a repeated revision identity is quarantined as failed, never published.
        try:
            await registry.assert_unique_revision(
                session,
                document_id=registration.document_id,
                version_id=registration.version_id,
                revision=parsed.meta.revision,
            )
        except registry.RevisionConflictError as exc:
            await registry.update_version(
                session,
                registration.version_id,
                pipeline_state="failed",
                failure_reason=str(exc),
            )
            return IngestResult(
                path=rel_path,
                doc_key=registration.doc_key,
                state="failed",
                reason=str(exc),
                stage_attempted=True,
            )

        chunks = chunk_document(parsed, content_hash=content_hash, settings=self.settings.retrieval)
        self._put_artifact(
            registration.doc_key,
            content_hash,
            "chunks.json",
            json.dumps([asdict(c) for c in chunks], indent=1).encode(),
        )

        doc_metrics = compute_metrics(
            parsed,
            chunks,
            sanitize_hits=sanitize_hits,
            seconds=time.monotonic() - started,
        )
        self._put_artifact(
            registration.doc_key,
            content_hash,
            "metrics.json",
            json.dumps(doc_metrics.as_dict(), indent=1).encode(),
        )
        try:
            enforce_gates(doc_metrics)
        except IngestGateError as exc:
            await registry.update_version(
                session,
                registration.version_id,
                pipeline_state="failed",
                failure_reason=str(exc),
                metrics=doc_metrics.as_dict(),
            )
            return IngestResult(
                path=rel_path,
                doc_key=registration.doc_key,
                state="failed",
                reason=str(exc),
                stage_attempted=True,
            )

        await registry.replace_chunks(session, registration.version_id, chunks)
        await registry.update_version(
            session,
            registration.version_id,
            pipeline_state="chunked",
            metrics=doc_metrics.as_dict(),
        )

        n_points = await indexer.index_chunks(
            self.qdrant,
            self.settings.qdrant,
            self.embeddings,
            doc_key=registration.doc_key,
            doc_type=parsed.meta.doc_type,
            title=parsed.meta.title,
            revision=parsed.meta.revision,
            version_id=registration.version_id,
            chunks=chunks,
            effective_from=effective_from,
            batch_size=self.settings.retrieval.index_batch_size,
        )
        await registry.update_version(
            session,
            registration.version_id,
            pipeline_state="indexed",
            metrics=doc_metrics.as_dict(),
            processing_config_hash=self._processing_config_hash(),
        )
        restored = registration.tombstoned and await registry.restore_document(
            session, document_id=registration.document_id, version_id=registration.version_id
        )
        await self._settle_lifecycles(session, registration.document_id)
        await write_audit_event(
            session,
            AuditEvent(
                actor=_AUDIT_ACTOR,
                action="document_indexed",
                payload={
                    "doc_key": registration.doc_key,
                    "content_hash": content_hash,
                    "n_points": n_points,
                    "restored": restored,
                },
            ),
        )
        return IngestResult(
            path=rel_path,
            doc_key=registration.doc_key,
            state="indexed",
            n_chunks=len(chunks),
            stage_attempted=True,
        )

    async def _parse(
        self, parser: DocumentParser | AsyncDocumentParser, path: Path, meta: DocMeta
    ) -> ParsedDocument:
        """Dispatch to the parser, then verify PDF page coverage. A born-digital
        PDF that turns out to be a scan (no text layer) is retried through the
        OCR parser, with the detour recorded as a warning. A hybrid PDF, whose
        born-digital parse succeeds but leaves image-only pages behind, has those
        pages recovered through the same OCR path. Whatever the path, a PDF must
        end with a block for every physical page or the parse fails loudly."""
        parsed = await self._dispatch_parser(parser, path, meta)
        return _require_full_pdf_coverage(parsed)

    async def _dispatch_parser(
        self, parser: DocumentParser | AsyncDocumentParser, path: Path, meta: DocMeta
    ) -> ParsedDocument:
        if isinstance(parser, AsyncDocumentParser):
            return await parser.parse(path, meta)
        try:
            parsed = parser.parse(path, meta)
        except NoTextLayerError:
            scanned = await self.router.scanned.parse(path, meta)
            warning = "no text layer found by born-digital parser; parsed via OCR path"
            return replace(scanned, warnings=(warning, *scanned.warnings))
        if isinstance(parser, PdfFormParser):
            return await self._recover_scanned_pages(path, meta, parsed)
        return parsed

    async def _recover_scanned_pages(
        self, path: Path, meta: DocMeta, parsed: ParsedDocument
    ) -> ParsedDocument:
        """OCR the image-only pages of a hybrid PDF that the born-digital parser
        could not read. Without this, an inserted scan in an otherwise
        born-digital document is dropped with only a warning and its evidence
        never reaches retrieval; the recovered pages also carry an OCR
        confidence so the ingestion gate can still block a degraded scan."""
        covered = {block.page for block in parsed.blocks if block.page is not None}
        supplement = await self.router.scanned.ocr_selected_pages(path, meta, exclude_pages=covered)
        if supplement is None:
            return parsed
        merged_blocks = tuple(
            sorted((*parsed.blocks, *supplement.blocks), key=lambda block: block.page or 0)
        )
        warning = f"{len(supplement.blocks)} image-only page(s) recovered via per-page OCR fallback"
        return replace(
            parsed,
            blocks=merged_blocks,
            attributes={**parsed.attributes, **supplement.attributes},
            warnings=(*parsed.warnings, warning, *supplement.warnings),
        )

    async def _version_state(self, session: AsyncSession, version_id: str) -> str:
        row = (
            await session.execute(
                text("SELECT pipeline_state FROM app.document_versions WHERE id = :id"),
                {"id": version_id},
            )
        ).one()
        return str(row.pipeline_state)

    async def _settle_lifecycles(self, session: AsyncSession, document_id: str) -> None:
        """Settle which revision of the document is in force, then write every
        indexed version's lifecycle onto its points. index_chunks always writes
        status=effective, so a reindexed superseded revision would otherwise
        stay effective in the index while the registry records it obsolete."""
        await registry.reconcile_document_versions(session, document_id)
        lifecycles = await registry.indexed_version_lifecycles(session, document_id)
        await indexer.apply_supersessions(self.qdrant, self.settings.qdrant, lifecycles)

    def _processing_config_hash(self) -> str:
        return processing_config_hash(
            self.settings, embedding_implementation=type(self.embeddings).__name__
        )

    async def _processing_config_matches(self, session: AsyncSession, version_id: str) -> bool:
        """True when the version was indexed under the current processing config.
        A NULL stored hash (indexed before the column existed) never matches, so
        such a version is rebuilt once and stamped with the current config."""
        row = (
            await session.execute(
                text("SELECT processing_config_hash FROM app.document_versions WHERE id = :id"),
                {"id": version_id},
            )
        ).one()
        stored = row.processing_config_hash
        return stored is not None and stored == self._processing_config_hash()

    async def _indexed_points_in_sync(self, session: AsyncSession, version_id: str) -> bool:
        """True when an already-indexed version's live Qdrant point count still
        matches the child chunks the registry recorded. Content-hash idempotency
        skips re-indexing an 'indexed' version, so a version whose points went
        missing (a delete that outran its upsert, a drifted collection) must be
        detected here and rebuilt rather than reported unchanged."""
        expected = int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) AS n FROM app.chunks "
                        "WHERE document_version_id = :v AND chunk_type <> 'parent'"
                    ),
                    {"v": version_id},
                )
            )
            .one()
            .n
        )
        actual = (
            await self.qdrant.count(
                collection_name=self.settings.qdrant.collection,
                count_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="version_id", match=models.MatchValue(value=version_id)
                        )
                    ]
                ),
                exact=True,
            )
        ).count
        return classify_drift(expected, actual) is None

    def _put_artifact(self, doc_key: str, content_hash: str, name: str, data: bytes) -> None:
        self.object_store.put(
            self.settings.objectstore.bucket_artifacts,
            artifact_key(doc_key, content_hash, name),
            data,
        )


def _sanitize_document(parsed: ParsedDocument) -> tuple[ParsedDocument, int]:
    """Neutralize instruction-like text in every extracted string, not just
    block bodies. The title, document attributes, and per-block fields all flow
    downstream — the title into the context header that is embedded and
    reranked, attributes into effective-date/template decisions, fields into
    stored payloads — so an injection carried in any of them is as dangerous as
    one in the body and must be redacted before it derives anything."""
    from gg_ingestion.sanitize import sanitize_text

    hits = 0

    def clean(value: str) -> str:
        nonlocal hits
        result = sanitize_text(value)
        hits += len(result.hits)
        return result.text

    def clean_fields(values: dict[str, str]) -> dict[str, str]:
        return {key: clean(val) for key, val in values.items()}

    meta = replace(
        parsed.meta,
        title=clean(parsed.meta.title),
        revision=clean(parsed.meta.revision) if parsed.meta.revision else parsed.meta.revision,
    )
    attributes = clean_fields(parsed.attributes)
    blocks = tuple(
        replace(block, text=clean(block.text), fields=clean_fields(block.fields))
        for block in parsed.blocks
    )
    if hits == 0:
        return parsed, 0
    return replace(parsed, meta=meta, blocks=blocks, attributes=attributes), hits


def _parsed_to_json(parsed: ParsedDocument) -> bytes:
    return json.dumps(
        {
            "meta": asdict(parsed.meta),
            "parser": parsed.parser,
            "warnings": list(parsed.warnings),
            "attributes": parsed.attributes,
            "blocks": [asdict(b) for b in parsed.blocks],
        },
        indent=1,
    ).encode()
