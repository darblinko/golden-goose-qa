"""Agent state and the serializable shapes that cross node boundaries.

State values must survive the Postgres checkpointer, so retrieval results are
carried as plain dicts (see chunk_to_dict / parent_to_dict), never as the
frozen dataclasses from gg_retrieval.
"""

import hashlib
from typing import Any, TypedDict

from gg_retrieval.models import ParentContext, RetrievedChunk
from gg_retrieval.tools.external.models import ExternalResult
from gg_retrieval.tools.models import ToolResult

MAX_REWRITES = 2

PATTERNS = (
    "procedure",  # content of an SOP or work instruction
    "record",  # a specific record or its thread (CAPA, NCR, complaint, MDR)
    "revision",  # revision, approval, or effective-date questions
    "trace",  # requirement/training/reference walks — answered from the graph
    "fmea",  # DFMEA/PFMEA and risk questions
    "aggregate",  # counts and listings — answered from the record warehouse
    "external",  # public regulatory/scientific sources (FDA, eCFR, trials, PubMed, web)
    "compare",  # internal-vs-external rate comparison (warehouse + external together)
    "out_of_scope",  # greetings or questions unrelated to the QMS corpus
)

DEFAULT_PATTERN = "record"


class AgentState(TypedDict, total=False):
    question: str
    role: str  # caller's ACL role; every tool node filters through it
    history: list[dict[str, str]]  # prior turns: {"role": ..., "content": ...}
    query: str  # current retrieval query (diverges from question after rewrites)
    pattern: str
    doc_type: str | None
    doc_key: str | None  # exact document scope when the question names one document
    revision: str | None  # exact revision scope, only alongside a single doc_key
    as_of: str | None  # ISO date when the question targets a past effective state
    rewrites: int
    chunks: list[dict[str, Any]]
    parents: list[dict[str, Any]]
    external_parents: list[dict[str, Any]]  # external evidence, kept apart from QMS parents
    external_error: str | None  # set when the external fetch degraded; surfaced in the answer
    grade_sufficient: bool
    grade_reason: str
    answer: str
    citations: list[dict[str, Any]]
    verdict: str  # "grounded" | "insufficient_evidence" | "not_applicable"
    verifier_error: str | None
    regenerated: bool
    prompt_hash: str


def initial_state(
    question: str, history: list[dict[str, str]] | None = None, *, role: str = "qa_user"
) -> AgentState:
    """Fresh per-turn state. Every field is reset so a checkpointed thread
    never leaks a previous turn's answer, retrieval, or verdict."""
    return AgentState(
        question=question,
        role=role,
        history=history or [],
        query=question,
        pattern=DEFAULT_PATTERN,
        doc_type=None,
        doc_key=None,
        revision=None,
        as_of=None,
        rewrites=0,
        chunks=[],
        parents=[],
        external_parents=[],
        external_error=None,
        grade_sufficient=False,
        grade_reason="",
        answer="",
        citations=[],
        verdict="",
        verifier_error=None,
        regenerated=False,
        prompt_hash="",
    )


def chunk_to_dict(chunk: RetrievedChunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "doc_key": chunk.doc_key,
        "doc_type": chunk.doc_type,
        "section_path": chunk.section_path,
        "score": chunk.score,
        "parent_id": chunk.parent_id,
    }


def parent_to_dict(parent: ParentContext) -> dict[str, Any]:
    return {
        "parent_id": parent.parent_id,
        "doc_key": parent.doc_key,
        "doc_type": parent.doc_type,
        "title": parent.title,
        "revision": parent.revision,
        "section_path": parent.section_path,
        "page": parent.page,
        "text": parent.text,
        "matched_child_text": parent.matched_child_text,
        "version_id": parent.version_id,
        "citation": parent.citation,
        "best_child_score": parent.best_child_score,
        "provenance": "internal",
    }


def tool_parent_dict(result: ToolResult) -> dict[str, Any]:
    """Present a structured tool result as a synthetic parent so the existing
    generate/verify/citation machinery treats it like retrieved evidence.

    When a traversal read its rows from real documents, the citation names those
    document keys — the derived graph is the retrieval method, not the evidence.
    A result with no document provenance falls back to the source banner.
    """
    digest = hashlib.sha256(f"{result.tool}\x1e{result.query}".encode()).hexdigest()[:32]
    source_doc_keys = list(result.source_doc_keys)
    doc_key = ", ".join(source_doc_keys) if source_doc_keys else result.source
    return {
        "parent_id": f"tool-{digest}",
        "doc_key": doc_key,
        "doc_type": "tool_result",
        "title": result.title,
        "revision": "",
        "section_path": result.query,
        "page": None,
        "text": result.to_text(),
        "citation": f"{result.title} — {doc_key}",
        "best_child_score": 1.0,
        "source_doc_keys": source_doc_keys,
        "provenance": "internal",
    }


def external_parent_dict(result: ExternalResult) -> dict[str, Any]:
    """Present an external lookup as a synthetic parent. Provenance stays
    "external" end-to-end so these render apart from QMS citations."""
    digest = hashlib.sha256(f"{result.tool}\x1e{result.query}".encode()).hexdigest()[:32]
    return {
        "parent_id": f"external-{digest}",
        "doc_key": result.source,
        "doc_type": "external_result",
        "title": result.title,
        "revision": "",
        "section_path": result.query,
        "page": None,
        "text": result.to_text(),
        "citation": f"{result.title} — {result.source} [EXTERNAL]",
        "best_child_score": 1.0,
        "provenance": result.provenance,
    }


def citation_view(parent: dict[str, Any], marker: int) -> dict[str, Any]:
    """What the UI's citation panel needs — everything except the full text.

    source_doc_keys carries the verifiable document ids behind a graph/tool
    answer so the panel can link every claim to the file it was read from.
    """
    return {
        "marker": marker,
        "doc_key": parent["doc_key"],
        "doc_type": parent["doc_type"],
        "title": parent["title"],
        "revision": parent["revision"],
        "section_path": parent["section_path"],
        "page": parent["page"],
        "citation": parent["citation"],
        # The exact document version behind the citation, so the source viewer
        # can serve the revision the answer used rather than the current one.
        "version_id": parent.get("version_id"),
        "provenance": parent.get("provenance", "internal"),
        "source_doc_keys": parent.get("source_doc_keys", []),
    }
