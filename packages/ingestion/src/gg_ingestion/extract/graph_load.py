"""Idempotent Neo4j loading of extraction output.

Everything is MERGE-based: nodes on their key property, edges after merging
both endpoints, so re-deriving the same corpus is a no-op. Labels and
relationship types are interpolated into Cypher only from the whitelists in
extract.model — parameters carry all data values.
"""

from collections import defaultdict
from typing import Any

from gg_common.graphstore import run_write
from neo4j import AsyncDriver

from gg_ingestion.extract.model import NODE_KEY_PROPERTY, RELATIONSHIP_TYPES, Edge, Node


def node_query(label: str) -> str:
    if label not in NODE_KEY_PROPERTY:
        raise ValueError(f"unknown node label: {label}")
    key_property = NODE_KEY_PROPERTY[label]
    return (
        f"UNWIND $rows AS row MERGE (n:{label} {{{key_property}: row.key}}) SET n += row.properties"
    )


def edge_query(rel_type: str, start_label: str, end_label: str) -> str:
    if rel_type not in RELATIONSHIP_TYPES:
        raise ValueError(f"unknown relationship type: {rel_type}")
    if start_label not in NODE_KEY_PROPERTY or end_label not in NODE_KEY_PROPERTY:
        raise ValueError(f"unknown edge endpoint label: {start_label} / {end_label}")
    # The same fact can be asserted by two documents (a trace-matrix cell and
    # the verification report's own form field); the edge collapses to one and
    # a strictly-higher-confidence provenance overwrites. Equal confidence does
    # NOT overwrite (strict `<`), so a tie is first-writer-wins deterministically
    # rather than last-writer-wins; equal-confidence disagreements are surfaced
    # separately as conflicts (see `edge_conflicts`) instead of vanishing.
    return (
        f"UNWIND $rows AS row "
        f"MERGE (a:{start_label} {{{NODE_KEY_PROPERTY[start_label]}: row.start}}) "
        f"MERGE (b:{end_label} {{{NODE_KEY_PROPERTY[end_label]}: row.end}}) "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        f"ON CREATE SET r += row.properties "
        f"ON MATCH SET r += CASE "
        f"WHEN coalesce(r.confidence, -1.0) < row.properties.confidence "
        f"THEN row.properties ELSE {{}} END"
    )


def edge_properties(edge: Edge) -> dict[str, Any]:
    """Edge payload with provenance flattened in; None values dropped."""
    properties = {
        **edge.properties,
        "source_doc_key": edge.provenance.doc_key,
        "method": edge.provenance.method,
        "locator": edge.provenance.locator,
        "confidence": edge.provenance.confidence,
    }
    return {key: value for key, value in properties.items() if value is not None}


def _assertion_signature(edge: Edge) -> tuple[tuple[str, str], ...]:
    """The substantive assertion an edge makes, independent of which document
    made it — provenance fields are excluded so corroboration from two sources
    is not mistaken for a contradiction."""
    return tuple(sorted((str(key), repr(value)) for key, value in edge.properties.items()))


def edge_conflicts(edges: list[Edge]) -> list[str]:
    """Equal-confidence edges that assert *different* properties for the same
    relationship. The loader keeps the first such edge deterministically (a tie
    does not overwrite), so the losers' assertions are dropped — surfacing them
    here turns a silent collapse into an explicit conflict record. Edges that
    merely corroborate the same assertion from different sources are not
    conflicts and are omitted."""
    grouped: dict[tuple[str, str, str, str, str], list[Edge]] = defaultdict(list)
    for edge in edges:
        grouped[
            (edge.rel_type, edge.start_label, edge.start_key, edge.end_label, edge.end_key)
        ].append(edge)
    conflicts: list[str] = []
    for (rel_type, _start_label, start_key, _end_label, end_key), group in grouped.items():
        if len(group) < 2:
            continue
        top = max(edge.provenance.confidence for edge in group)
        contenders = [edge for edge in group if edge.provenance.confidence == top]
        distinct = {_assertion_signature(edge) for edge in contenders}
        if len(distinct) < 2:
            continue  # exact corroboration at the top rank — nothing is lost
        sources = ", ".join(sorted({edge.provenance.doc_key for edge in contenders}))
        conflicts.append(
            f"equal-confidence ({top}) conflict on {start_key} -[{rel_type}]-> {end_key}: "
            f"{len(distinct)} differing assertions from {sources}; "
            f"kept {contenders[0].provenance.doc_key}"
        )
    return conflicts


async def load_nodes(driver: AsyncDriver, nodes: list[Node]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        grouped[node.label].append({"key": node.key, "properties": node.properties})
    for label, rows in grouped.items():
        await run_write(driver, node_query(label), {"rows": rows})


async def load_edges(driver: AsyncDriver, edges: list[Edge]) -> list[str]:
    """Load edges idempotently and return any equal-confidence conflicts so the
    caller can surface them (the loader keeps the first, deterministically)."""
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        grouped[(edge.rel_type, edge.start_label, edge.end_label)].append(
            {
                "start": edge.start_key,
                "end": edge.end_key,
                "properties": edge_properties(edge),
            }
        )
    for (rel_type, start_label, end_label), rows in grouped.items():
        await run_write(driver, edge_query(rel_type, start_label, end_label), {"rows": rows})
    return edge_conflicts(edges)
