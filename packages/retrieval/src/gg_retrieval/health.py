"""Retrieval health probe: index counts plus a fixed end-to-end query.

Counts alone cannot catch a broken read path (wrong vector names, empty
payloads, registry drift), so the probe runs the real retriever against a
question every ingested corpus must answer.
"""

from typing import Any

from sqlalchemy import text

from gg_retrieval.drift import index_drift
from gg_retrieval.retriever import HybridRetriever

PROBE_QUERY = "What does the CAPA procedure require for effectiveness verification?"


async def retrieval_health(retriever: HybridRetriever) -> dict[str, Any]:
    collection = retriever.settings.qdrant.collection
    report: dict[str, Any] = {"collection": collection}

    try:
        count = await retriever.qdrant.count(collection_name=collection, exact=True)
        report["points"] = count.count
    except Exception as exc:
        report["points"] = 0
        report["qdrant_error"] = str(exc)

    try:
        async with retriever.session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT count(*) AS n FROM app.chunks WHERE chunk_type = 'parent'")
                )
            ).one()
            report["parents_in_registry"] = int(row.n)
    except Exception as exc:
        report["parents_in_registry"] = 0
        report["postgres_error"] = str(exc)

    try:
        result = await retriever.retrieve(PROBE_QUERY)
        report["probe"] = {
            "query": PROBE_QUERY,
            "n_chunks": len(result.chunks),
            "n_parents": len(result.parents),
            "top_doc": result.chunks[0].doc_key if result.chunks else None,
            "timings_ms": result.timings_ms,
        }
    except Exception as exc:
        report["probe"] = {"query": PROBE_QUERY, "error": str(exc)}

    try:
        report["drift"] = await index_drift(
            retriever.qdrant, retriever.session_factory, collection=collection
        )
    except Exception as exc:
        report["drift"] = {"error": str(exc)}

    probe: dict[str, Any] = report["probe"]
    drift: dict[str, Any] = report["drift"]
    report["healthy"] = (
        report["points"] > 0
        and report["parents_in_registry"] > 0
        and probe.get("n_chunks", 0) > 0
        and drift.get("in_sync", False)
    )
    return report
