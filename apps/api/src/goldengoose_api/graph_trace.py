"""Trace subgraph: the knowledge graph neighbourhood of one record, with the
provenance of every link, for the web app's Trace tab.

Labels and key property names are interpolated into Cypher only from
NODE_KEY_PROPERTY in gg_ingestion.extract.model; the anchor key and every node
reference travel as parameters. Three fixed queries fetch the anchor, the
incident edges of a node set, and the edges among the selected nodes;
neighbour selection, caps and ordering run here in Python.
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from gg_common.graphstore import run_read
from gg_ingestion.extract.model import NODE_KEY_PROPERTY
from neo4j import AsyncDriver

HOP1_LIMIT = 40
HOP2_PER_NODE_LIMIT = 8
EDGE_LIMIT = 150

# Extraction methods that mine links from free text; every other method in
# METHOD_CONFIDENCE reads a structured field.
TEXT_MINED_METHODS = frozenset({"references_section", "inline_regex"})

_KIND_BY_LABEL = {
    "DocumentRevision": "revision",
    "Requirement": "requirement",
    "DesignOutput": "design_output",
    "Supplier": "supplier",
    "Person": "person",
    "FmeaRow": "fmea_row",
}

# The loader stores no document body on graph nodes; these names are refused
# so a later loader that adds one does not leak it into the panel.
_BODY_PROPERTIES = frozenset({"body", "content", "full_text", "raw_text", "markdown"})

_LABEL_RE = re.compile(r"[A-Za-z]+")
_KEY_RE = re.compile(r"[A-Za-z0-9 ._/:-]{1,80}")

NEIGHBOURS_QUERY = """
MATCH (n)-[r]-(m)
WHERE elementId(n) IN $element_ids
RETURN elementId(n) AS from_id, r.confidence AS confidence,
       elementId(m) AS element_id, labels(m) AS labels, properties(m) AS properties,
       COUNT { (m)--() } AS degree
"""

EDGES_QUERY = """
MATCH (a)-[r]->(b)
WHERE elementId(a) IN $element_ids AND elementId(b) IN $element_ids
RETURN elementId(a) AS start_id, elementId(b) AS end_id, type(r) AS type,
       properties(r) AS properties
"""


@dataclass(frozen=True)
class Anchor:
    label: str
    key: str

    @property
    def node_id(self) -> str:
        return f"{self.label}:{self.key}"


@dataclass(frozen=True)
class GraphNode:
    element_id: str
    label: str
    key: str
    properties: dict[str, Any]
    degree: int

    @property
    def node_id(self) -> str:
        return f"{self.label}:{self.key}"


@dataclass(frozen=True)
class Candidate:
    node: GraphNode
    confidence: float


@dataclass(frozen=True)
class SelectedNode:
    node: GraphNode
    hop: int
    via: str | None  # element id of the node whose expansion selected this one


def parse_anchor(raw: str) -> Anchor:
    """`<Label>:<key>` when the text before the first colon is a bare word,
    otherwise the whole string is a Document key (keys may contain colons)."""
    prefix, separator, rest = raw.partition(":")
    if separator and _LABEL_RE.fullmatch(prefix):
        if prefix not in NODE_KEY_PROPERTY:
            raise ValueError(f"unknown label: {prefix}")
        label, key = prefix, rest
    else:
        label, key = "Document", raw
    if not _KEY_RE.fullmatch(key):
        raise ValueError(
            "anchor key must be 1 to 80 characters: letters, digits, space, or . _ / : -"
        )
    return Anchor(label=label, key=key)


def anchor_query(label: str) -> str:
    if label not in NODE_KEY_PROPERTY:
        raise ValueError(f"unknown node label: {label}")
    return (
        f"MATCH (n:{label} {{{NODE_KEY_PROPERTY[label]}: $key}}) "
        "RETURN elementId(n) AS element_id, properties(n) AS properties, "
        "COUNT { (n)--() } AS degree"
    )


async def trace_subgraph(driver: AsyncDriver, anchor: Anchor, hops: int) -> dict[str, Any] | None:
    """The response body for the anchor's neighbourhood, or None when no node
    has the anchor's key."""
    found = await run_read(driver, anchor_query(anchor.label), {"key": anchor.key})
    if not found:
        return None
    root = GraphNode(
        element_id=found[0]["element_id"],
        label=anchor.label,
        key=anchor.key,
        properties=dict(found[0]["properties"]),
        degree=int(found[0]["degree"]),
    )
    selected, nodes_truncated = await _select_nodes(driver, root, hops)
    edge_rows = await run_read(
        driver, EDGES_QUERY, {"element_ids": [entry.node.element_id for entry in selected]}
    )
    edges, edges_truncated = select_edges(edge_rows, selected)
    endpoint_counts = Counter(end for edge in edges for end in (edge["source"], edge["target"]))
    return {
        "anchor": anchor.node_id,
        "hops": hops,
        "nodes": [node_out(entry, endpoint_counts[entry.node.node_id]) for entry in selected],
        "edges": edges,
        "truncated": nodes_truncated or edges_truncated,
    }


async def _select_nodes(
    driver: AsyncDriver, root: GraphNode, hops: int
) -> tuple[list[SelectedNode], bool]:
    hop1_rows = await run_read(driver, NEIGHBOURS_QUERY, {"element_ids": [root.element_id]})
    hop1, truncated = pick_neighbours(
        neighbours_by_origin(hop1_rows).get(root.element_id, []),
        excluded={root.element_id},
        limit=HOP1_LIMIT,
    )
    selected = [SelectedNode(root, 0, None)]
    selected += [SelectedNode(candidate.node, 1, root.element_id) for candidate in hop1]
    if hops < 2 or not hop1:
        return selected, truncated

    hop2_rows = await run_read(
        driver, NEIGHBOURS_QUERY, {"element_ids": [c.node.element_id for c in hop1]}
    )
    by_origin = neighbours_by_origin(hop2_rows)
    taken = {entry.node.element_id for entry in selected}
    for origin in hop1:
        picked, capped = pick_neighbours(
            by_origin.get(origin.node.element_id, []),
            excluded=taken,
            limit=HOP2_PER_NODE_LIMIT,
        )
        truncated = truncated or capped
        selected += [SelectedNode(c.node, 2, origin.node.element_id) for c in picked]
        taken |= {c.node.element_id for c in picked}
    return selected, truncated


def neighbours_by_origin(rows: list[dict[str, Any]]) -> dict[str, list[Candidate]]:
    """Group incident-edge rows by the queried node. A neighbour reached over
    several edges appears once, ranked by its highest-confidence edge."""
    best: dict[str, dict[str, Candidate]] = {}
    for row in rows:
        node = graph_node(row)
        if node is None:
            continue
        confidence = _number(row.get("confidence")) or 0.0
        by_neighbour = best.setdefault(row["from_id"], {})
        current = by_neighbour.get(node.element_id)
        if current is None or confidence > current.confidence:
            by_neighbour[node.element_id] = Candidate(node, confidence)
    return {origin: list(found.values()) for origin, found in best.items()}


def pick_neighbours(
    candidates: list[Candidate], *, excluded: set[str], limit: int
) -> tuple[list[Candidate], bool]:
    """Up to `limit` candidates not yet selected, by edge confidence descending
    then key; the flag is true when the limit dropped any."""
    eligible = sorted(
        (c for c in candidates if c.node.element_id not in excluded),
        key=lambda c: (-c.confidence, c.node.key, c.node.label),
    )
    return eligible[:limit], len(eligible) > limit


def graph_node(row: dict[str, Any]) -> GraphNode | None:
    """A neighbour row as a node, or None when it carries no whitelisted label
    or lacks that label's key property."""
    label = next((name for name in row.get("labels") or () if name in NODE_KEY_PROPERTY), None)
    if label is None:
        return None
    properties = dict(row.get("properties") or {})
    key = properties.get(NODE_KEY_PROPERTY[label])
    if key is None:
        return None
    return GraphNode(
        element_id=row["element_id"],
        label=label,
        key=str(key),
        properties=properties,
        degree=int(row.get("degree") or 0),
    )


def select_edges(
    rows: list[dict[str, Any]], selected: list[SelectedNode]
) -> tuple[list[dict[str, Any]], bool]:
    """Relationships among the selected nodes, capped at EDGE_LIMIT. Links to
    the anchor rank first, then the link that brought each hop-2 node in, then
    cross links, so the cap removes the least explanatory links first."""
    by_element = {entry.node.element_id: entry for entry in selected}
    ranked = []
    for row in rows:
        start = by_element.get(row["start_id"])
        end = by_element.get(row["end_id"])
        if start is None or end is None:
            continue
        edge = edge_out(start.node, end.node, str(row["type"]), row.get("properties") or {})
        ranked.append((_edge_tier(start, end), -(edge["confidence"] or 0.0), edge["id"], edge))
    ranked.sort(key=lambda item: item[:3])
    return [item[3] for item in ranked[:EDGE_LIMIT]], len(ranked) > EDGE_LIMIT


def _edge_tier(start: SelectedNode, end: SelectedNode) -> int:
    if start.hop == 0 or end.hop == 0:
        return 0
    if start.via == end.node.element_id or end.via == start.node.element_id:
        return 1
    return 2


def edge_out(
    start: GraphNode, end: GraphNode, rel_type: str, properties: dict[str, Any]
) -> dict[str, Any]:
    method = _text(properties.get("method"))
    return {
        "id": f"{start.node_id}|{rel_type}|{end.node_id}",
        "source": start.node_id,
        "target": end.node_id,
        "type": rel_type,
        "method": method,
        "locator": _text(properties.get("locator")),
        "source_doc_key": _text(properties.get("source_doc_key")),
        "confidence": _number(properties.get("confidence")),
        "inferred": method in TEXT_MINED_METHODS,
    }


def node_out(entry: SelectedNode, returned_edges: int) -> dict[str, Any]:
    node = entry.node
    title = node.properties.get("title")
    return {
        "id": node.node_id,
        "label": node.label,
        "key": node.key,
        "title": title if isinstance(title, str) and title else None,
        "kind": node_kind(node.label, node.properties),
        "hop": entry.hop,
        "degree": node.degree,
        "hidden_links": max(0, node.degree - returned_edges),
        "properties": display_properties(node.label, node.properties),
    }


def node_kind(label: str, properties: dict[str, Any]) -> str:
    if label == "Document":
        doc_type = properties.get("doc_type")
        return str(doc_type).lower() if doc_type else "document"
    return _KIND_BY_LABEL[label]


def display_properties(label: str, properties: dict[str, Any]) -> dict[str, Any]:
    """Scalar properties for the panel, without the key, the title (returned
    on its own) or any body text. Dates become ISO strings."""
    hidden = {NODE_KEY_PROPERTY[label], "title", *_BODY_PROPERTIES}
    shown: dict[str, Any] = {}
    for name in sorted(properties):
        value = _scalar(properties[name])
        if name not in hidden and value is not None:
            shown[name] = value
    return shown


def _scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, str | int | float | bool):
        return value
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return None


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _number(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None
