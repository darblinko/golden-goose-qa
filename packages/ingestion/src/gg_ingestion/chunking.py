"""Structural parent-child chunking.

Children (~350 tokens, heading/row/page boundaries) are what gets indexed and
retrieved; parents (full section, capped ~2000 tokens) are what the generator
reads. Every chunk carries a deterministic context header (document identity +
section) prepended at embedding time — the structural half of contextual
retrieval, present even when no LLM is available to write a semantic preamble.

Chunk IDs are UUIDv5 over (doc_key, content_hash, ordinal): stable across
re-runs of the same bytes, disjoint across revisions, and — critically —
disjoint across documents that happen to share identical bytes, so two doc_keys
with the same content never collide on chunk id (the chunks PK) or Qdrant point.
"""

import uuid
from collections.abc import Iterator

from gg_common.settings import RetrievalSettings

from gg_ingestion.models import Chunk, ParsedBlock, ParsedDocument

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "chunks.goldengoose.local")

_FMEA_BANNER = (
    "AIAG-VDA FMEA worksheet; AP is Action Priority derived from "
    "Severity (S), Occurrence (O), Detection (D)."
)


def _tokens(text: str) -> int:
    return len(text.split())


def _chunk_id(seed: str, ordinal: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{seed}:{ordinal}"))


def _context_header(parsed: ParsedDocument) -> str:
    meta = parsed.meta
    rev = f" Rev {meta.revision}" if meta.revision else ""
    header = f"{meta.doc_key}{rev} — {meta.title} ({meta.doc_type})"
    if parsed.attributes.get("template") == "fmea":
        header = f"{header}. {_FMEA_BANNER}"
    return header


def _split_text(text: str, limit: int) -> Iterator[str]:
    words = text.split()
    for start in range(0, len(words), limit):
        yield " ".join(words[start : start + limit])


def _char_split(text: str, budget: int) -> list[str]:
    """Greedily pack whitespace-delimited tokens into pieces no longer than
    `budget` characters, hard-splitting only a single token that itself exceeds
    the budget."""
    pieces: list[str] = []
    current: list[str] = []
    used = 0
    for token in text.split():
        if len(token) > budget:
            if current:
                pieces.append(" ".join(current))
                current, used = [], 0
            pieces.extend(token[i : i + budget] for i in range(0, len(token), budget))
            continue
        extra = len(token) + (1 if current else 0)
        if current and used + extra > budget:
            pieces.append(" ".join(current))
            current, used = [], 0
            extra = len(token)
        current.append(token)
        used += extra
    if current:
        pieces.append(" ".join(current))
    return pieces


def _fit_to_char_ceiling(text: str, *, header_len: int, ceiling: int) -> list[str]:
    """Split `text` so that a context header plus separator plus the piece stays
    within `ceiling` characters. Ordinary chunks fall well under the ceiling and
    pass through unchanged; only a pathologically large child is fragmented."""
    budget = ceiling - header_len - len("\n\n")
    budget = max(1, budget)
    if len(text) <= budget:
        return [text]
    return _char_split(text, budget) or [text]


class _Section:
    def __init__(self, section_path: str, page: int | None = None) -> None:
        self.section_path = section_path
        self.page = page
        self.blocks: list[ParsedBlock] = []

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


def _narrative_sections(parsed: ParsedDocument) -> list[_Section]:
    sections: list[_Section] = []
    current = _Section("Document header")
    for block in parsed.blocks:
        if block.kind == "heading" and block.heading_level >= 2:
            if current.blocks:
                sections.append(current)
            current = _Section(block.section_path or block.text)
        current.blocks.append(block)
    if current.blocks:
        sections.append(current)
    return sections


def _row_sections(parsed: ParsedDocument, parent_tokens: int) -> list[_Section]:
    """Rows batched into parent-sized groups, preserving worksheet order."""
    sections: list[_Section] = []
    current = _Section("rows")
    used = 0
    for block in parsed.blocks:
        block_tokens = _tokens(block.text)
        if current.blocks and used + block_tokens > parent_tokens:
            sections.append(current)
            current = _Section("rows")
            used = 0
        current.blocks.append(block)
        used += block_tokens
    if current.blocks:
        sections.append(current)
    for i, section in enumerate(sections, start=1):
        first = section.blocks[0].section_path
        last = section.blocks[-1].section_path
        section.section_path = first if first == last else f"{first} .. {last} (part {i})"
    return sections


def _page_sections(parsed: ParsedDocument) -> list[_Section]:
    sections = []
    for block in parsed.blocks:
        section = _Section(f"page {block.page}", page=block.page)
        section.blocks.append(block)
        sections.append(section)
    return sections


def chunk_document(
    parsed: ParsedDocument,
    *,
    content_hash: str,
    settings: RetrievalSettings,
) -> list[Chunk]:
    header = _context_header(parsed)
    # Seed chunk ids with the document identity as well as the bytes: two
    # distinct doc_keys with identical content must not produce colliding ids.
    seed = f"{parsed.meta.doc_key}:{content_hash}"
    kinds = {b.kind for b in parsed.blocks}

    if kinds <= {"row"}:
        sections = _row_sections(parsed, settings.parent_chunk_tokens)
        child_type = "row"
    elif kinds <= {"page"}:
        sections = _page_sections(parsed)
        child_type = "page"
    else:
        sections = _narrative_sections(parsed)
        child_type = "child"

    chunks: list[Chunk] = []
    ordinal = 0
    for section in sections:
        if child_type == "row" or _tokens(section.text) <= settings.parent_chunk_tokens:
            # Keep original text (row sections are pre-batched; _split_text
            # would collapse the newlines block packing depends on).
            parent_texts = [section.text]
        else:
            parent_texts = list(_split_text(section.text, settings.parent_chunk_tokens))
        for parent_text in parent_texts:
            parent_id = _chunk_id(seed, ordinal)
            chunks.append(
                Chunk(
                    chunk_id=parent_id,
                    ordinal=ordinal,
                    chunk_type="parent",
                    section_path=section.section_path,
                    text=parent_text,
                    context_header=header,
                    token_count=_tokens(parent_text),
                    page=section.page,
                )
            )
            ordinal += 1
            ordinal = _append_children(
                chunks,
                section=section,
                parent_id=parent_id,
                parent_text=parent_text,
                child_type=child_type,
                header=header,
                seed=seed,
                ordinal=ordinal,
                child_tokens=settings.child_chunk_tokens,
                max_embed_chars=settings.max_embed_chars,
            )
    return chunks


def _append_children(
    chunks: list[Chunk],
    *,
    section: _Section,
    parent_id: str,
    parent_text: str,
    child_type: str,
    header: str,
    seed: str,
    ordinal: int,
    child_tokens: int,
    max_embed_chars: int,
) -> int:
    header_len = len(header)
    if child_type == "row":
        for block in section.blocks:
            for piece in _fit_to_char_ceiling(
                block.text, header_len=header_len, ceiling=max_embed_chars
            ):
                chunks.append(
                    Chunk(
                        chunk_id=_chunk_id(seed, ordinal),
                        ordinal=ordinal,
                        chunk_type="row",
                        section_path=block.section_path,
                        text=piece,
                        context_header=header,
                        token_count=_tokens(piece),
                        parent_id=parent_id,
                        payload={"fields": block.fields, "row_number": block.row_number},
                    )
                )
                ordinal += 1
        return ordinal

    if parent_text == section.text:
        packed = _pack_blocks(section.blocks, child_tokens)
    else:
        packed = list(_split_text(parent_text, child_tokens))
    pieces = [
        fitted
        for piece in packed
        for fitted in _fit_to_char_ceiling(piece, header_len=header_len, ceiling=max_embed_chars)
    ]
    for piece in pieces:
        chunks.append(
            Chunk(
                chunk_id=_chunk_id(seed, ordinal),
                ordinal=ordinal,
                chunk_type="page" if child_type == "page" else "child",
                section_path=section.section_path,
                text=piece,
                context_header=header,
                token_count=_tokens(piece),
                parent_id=parent_id,
                page=section.page,
            )
        )
        ordinal += 1
    return ordinal


def _pack_blocks(blocks: list[ParsedBlock], limit: int) -> list[str]:
    """Children on block (paragraph/heading/table) boundaries; only a single
    oversized block is ever split mid-text."""
    groups: list[str] = []
    current: list[str] = []
    used = 0
    for block in blocks:
        block_tokens = _tokens(block.text)
        if block_tokens > limit:
            if current:
                groups.append("\n".join(current))
                current, used = [], 0
            groups.extend(_split_text(block.text, limit))
            continue
        if current and used + block_tokens > limit:
            groups.append("\n".join(current))
            current, used = [], 0
        current.append(block.text)
        used += block_tokens
    if current:
        groups.append("\n".join(current))
    return groups
