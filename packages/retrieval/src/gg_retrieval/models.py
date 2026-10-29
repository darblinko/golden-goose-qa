"""Result shapes returned by the retriever.

Children are what matched; parents are what the generator reads. Both carry
full document identity so every generated claim can cite doc_key, revision,
and section without another lookup.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    doc_key: str
    doc_type: str
    title: str
    revision: str | None
    section_path: str
    text: str
    context_header: str
    score: float
    parent_id: str | None = None
    page: int | None = None
    version_id: str | None = None


@dataclass(frozen=True)
class ParentContext:
    parent_id: str
    doc_key: str
    doc_type: str
    title: str
    revision: str | None
    section_path: str
    text: str
    context_header: str
    best_child_score: float
    page: int | None = None
    # The document version this parent belongs to, so a citation resolves to the
    # exact revision the answer used — not whatever version is current now.
    version_id: str | None = None
    # Verbatim text of the highest-scoring child that matched under this parent.
    # The generator sees a clipped parent excerpt; carrying the matched passage
    # lets the prompt guarantee it is present even when clipping would drop it.
    matched_child_text: str | None = None

    @property
    def citation(self) -> str:
        rev = f" Rev {self.revision}" if self.revision else ""
        where = f", {self.section_path}" if self.section_path else ""
        page = f", p. {self.page}" if self.page is not None else ""
        return f"{self.doc_key}{rev}{where}{page}"


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    chunks: tuple[RetrievedChunk, ...]
    parents: tuple[ParentContext, ...]
    timings_ms: dict[str, float] = field(default_factory=dict)
    # Per-stage counts (candidates, entered_rerank, reranked, parents) plus an
    # `expanded` flag, so a thin or empty answer can be diagnosed — too few
    # candidates, or everything dropped by the score floor — without re-running
    # retrieval. Mirrors what the retrieval spans record.
    trace: dict[str, object] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.chunks
