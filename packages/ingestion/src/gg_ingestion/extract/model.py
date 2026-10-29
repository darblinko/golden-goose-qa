"""Shapes produced by deterministic extraction.

Every edge carries provenance (where in which document it was read from,
by which method) and a confidence reflecting how deterministic that method
is — a trace-matrix cell outranks an inline regex hit.
"""

from dataclasses import dataclass, field
from typing import Any

# Confidence by extraction method, most deterministic first (architecture §8).
METHOD_CONFIDENCE = {
    "trace_matrix": 1.0,
    "fmea_sheet": 1.0,
    "supplier_list": 1.0,
    "training_grid": 1.0,
    "control_plan": 1.0,
    "form_field": 0.95,
    "revision_table": 0.95,
    "references_section": 0.85,
    "inline_regex": 0.7,
}

NODE_KEY_PROPERTY = {
    "Document": "doc_key",
    "DocumentRevision": "key",
    "Requirement": "req_id",
    "DesignOutput": "do_id",
    "Supplier": "supplier_id",
    "Person": "name",
    "FmeaRow": "key",
}

RELATIONSHIP_TYPES = frozenset(
    {
        "HAS_REVISION",
        "SUPERSEDES",
        "REFERENCES",
        "SATISFIES",
        "VERIFIES",
        "HAS_ROW",
        "MITIGATED_BY",
        "ESCALATED_TO",
        "SOURCED_FROM",
        "FROM_SUPPLIER",
        "FILED_AS",
        "FROM_COMPLAINT",
        "SUBMISSION_OF",
        "EVALUATED_AGAINST",
        "AUDITS",
        "REVIEWED",
        "CONTROLLED_BY",
        "REALIZED_IN",
        "LISTS",
        "TRAINED_ON",
    }
)


@dataclass(frozen=True)
class Provenance:
    doc_key: str
    method: str
    locator: str

    @property
    def confidence(self) -> float:
        return METHOD_CONFIDENCE[self.method]


@dataclass(frozen=True)
class Node:
    label: str
    key: str
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.label not in NODE_KEY_PROPERTY:
            raise ValueError(f"unknown node label: {self.label}")


@dataclass(frozen=True)
class Edge:
    rel_type: str
    start_label: str
    start_key: str
    end_label: str
    end_key: str
    provenance: Provenance
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.rel_type not in RELATIONSHIP_TYPES:
            raise ValueError(f"unknown relationship type: {self.rel_type}")


@dataclass(frozen=True)
class RegisterRow:
    table: str
    values: dict[str, Any]


@dataclass(frozen=True)
class DocExtraction:
    doc_key: str
    doc_type: str
    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()
    register_rows: tuple[RegisterRow, ...] = ()
    dangling_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
