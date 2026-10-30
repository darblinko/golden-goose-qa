"""Derivation pass: parsed artifacts → knowledge graph + register warehouse.

Runs after ingestion against the registry's latest indexed version of every
document, reading the parse.json each version already produced — extraction
never re-parses source bytes, so graph and warehouse always describe exactly
what retrieval indexed.
"""

import json
from dataclasses import dataclass
from datetime import date

from gg_common.audit import AuditEvent, write_audit_event
from gg_common.objectstore import ObjectStore
from gg_common.settings import AppSettings
from neo4j import AsyncDriver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gg_ingestion.artifacts import artifact_key
from gg_ingestion.extract.extractors import extract_document
from gg_ingestion.extract.graph_load import replace_graph
from gg_ingestion.extract.model import DocExtraction, Edge, Node
from gg_ingestion.extract.warehouse_load import load_registers
from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument

_AUDIT_ACTOR = "derive-pipeline"


@dataclass(frozen=True)
class RegistryDocument:
    doc_key: str
    doc_type: str
    title: str
    content_hash: str
    revision: str | None
    effective_from: date | None


@dataclass(frozen=True)
class DeriveReport:
    documents: int
    # Assertions emitted, before the graph load merges duplicates by key; not
    # the node and relationship counts stored in the graph.
    nodes: int
    edges: int
    register_rows: int
    graph_loaded: bool
    dangling_refs: dict[str, tuple[str, ...]]
    warnings: tuple[str, ...]


def parsed_from_artifact(data: bytes) -> ParsedDocument:
    payload = json.loads(data)
    return ParsedDocument(
        meta=DocMeta(**payload["meta"]),
        blocks=tuple(ParsedBlock(**block) for block in payload["blocks"]),
        parser=payload["parser"],
        warnings=tuple(payload["warnings"]),
        attributes=payload["attributes"],
    )


async def indexed_documents(
    session: AsyncSession, today: date | None = None
) -> list[RegistryDocument]:
    """The indexed version in force today per doc_key, chosen by the same
    [effective_from, effective_to) window retrieval uses, so a revision
    published ahead of its effective date is not derived early. Graph and
    registers describe present QMS state; superseded revisions contribute
    nothing here (their history already lives in the effective document's
    revision-history table). A document with no version in force today (only
    a future revision, or only obsolete ones) is omitted. Tombstoned documents
    are excluded, so a retired source drops out of the graph and warehouse on
    the next rebuild."""
    rows = await session.execute(
        text(
            """
            SELECT DISTINCT ON (d.doc_key)
                d.doc_key, d.doc_type, d.title,
                v.content_hash, v.revision, v.effective_from
            FROM app.documents d
            JOIN app.document_versions v ON v.document_id = d.id
            WHERE v.pipeline_state = 'indexed' AND d.deleted_at IS NULL
              AND v.status = 'effective'
              AND (v.effective_from IS NULL OR v.effective_from <= :today)
              AND (v.effective_to IS NULL OR v.effective_to > :today)
            ORDER BY d.doc_key, v.effective_from DESC NULLS LAST, v.created_at DESC
            """
        ),
        {"today": today or date.today()},
    )
    return [
        RegistryDocument(
            doc_key=row.doc_key,
            doc_type=row.doc_type,
            title=row.title,
            content_hash=row.content_hash,
            revision=row.revision,
            effective_from=row.effective_from,
        )
        for row in rows
    ]


def document_node(doc: RegistryDocument) -> Node:
    properties = {
        "doc_type": doc.doc_type,
        "title": doc.title,
        "revision": doc.revision,
        "effective_from": doc.effective_from.isoformat() if doc.effective_from else None,
    }
    return Node(
        label="Document",
        key=doc.doc_key,
        properties={k: v for k, v in properties.items() if v is not None},
    )


def _graph_assertions(
    documents: list[RegistryDocument], extractions: list[DocExtraction]
) -> tuple[list[Node], list[Edge]]:
    nodes: list[Node] = [document_node(doc) for doc in documents]
    edges: list[Edge] = []
    for extraction in extractions:
        nodes.extend(extraction.nodes)
        edges.extend(extraction.edges)
    return nodes, edges


async def derive_corpus(
    *,
    settings: AppSettings,
    session_factory: async_sessionmaker[AsyncSession],
    object_store: ObjectStore,
    graph: AsyncDriver | None,
) -> DeriveReport:
    async with session_factory() as session:
        documents = await indexed_documents(session)
    known = frozenset(doc.doc_key for doc in documents)

    extractions: list[DocExtraction] = []
    for doc in documents:
        artifact = object_store.get(
            settings.objectstore.bucket_artifacts,
            artifact_key(doc.doc_key, doc.content_hash, "parse.json"),
        )
        extractions.append(extract_document(parsed_from_artifact(artifact), known))

    all_nodes, all_edges = _graph_assertions(documents, extractions)
    edge_conflicts: list[str] = []

    # Registers and graph are rebuildable projections of the same documents.
    # The register rows stay uncommitted until the graph transaction commits,
    # so a failed graph load rolls both back and leaves the previous, mutually
    # consistent projections in place.
    async with session_factory() as session:
        inserted = await load_registers(session, extractions)
        await write_audit_event(
            session,
            AuditEvent(
                actor=_AUDIT_ACTOR,
                action="registers_derived",
                payload={"documents": len(documents), "rows": inserted},
            ),
        )
        if graph is not None:
            edge_conflicts = await replace_graph(graph, all_nodes, all_edges)
            await write_audit_event(
                session,
                AuditEvent(
                    actor=_AUDIT_ACTOR,
                    action="graph_derived",
                    payload={"nodes": len(all_nodes), "edges": len(all_edges)},
                ),
            )
        await session.commit()

    dangling = {e.doc_key: e.dangling_refs for e in extractions if e.dangling_refs}
    warnings = tuple(
        f"{e.doc_key}: {warning}" for e in extractions for warning in e.warnings
    ) + tuple(f"graph: {conflict}" for conflict in edge_conflicts)
    return DeriveReport(
        documents=len(documents),
        nodes=len(all_nodes),
        edges=len(all_edges),
        register_rows=inserted,
        graph_loaded=graph is not None,
        dangling_refs=dangling,
        warnings=warnings,
    )
