"""Data shapes passed between ingestion stages.

Everything is a frozen dataclass: stages communicate through values (and JSON
artifacts of these values), never shared mutable state.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

BlockKind = Literal["heading", "paragraph", "table", "row", "page"]


@dataclass(frozen=True)
class ParsedBlock:
    """One structural unit produced by a parser, in document order."""

    kind: BlockKind
    text: str
    section_path: str = ""
    heading_level: int = 0
    page: int | None = None
    fields: dict[str, str] = field(default_factory=dict)
    row_number: int | None = None


@dataclass(frozen=True)
class DocMeta:
    """Identity extracted from filename and content before parsing."""

    doc_key: str
    doc_type: str
    title: str
    revision: str | None = None
    file_format: str = ""


@dataclass(frozen=True)
class ParsedDocument:
    meta: DocMeta
    blocks: tuple[ParsedBlock, ...]
    parser: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    """A parent or child chunk ready for storage and (children) indexing."""

    chunk_id: str
    ordinal: int
    chunk_type: Literal["parent", "child", "row", "page"]
    section_path: str
    text: str
    context_header: str
    token_count: int
    parent_id: str | None = None
    page: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def embed_text(self) -> str:
        """What actually gets embedded and sparse-indexed."""
        if self.context_header:
            return f"{self.context_header}\n\n{self.text}"
        return self.text
