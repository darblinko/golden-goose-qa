import uuid

from gg_common.settings import RetrievalSettings
from gg_ingestion.chunking import chunk_document
from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument

HASH_A = "a" * 64
HASH_B = "b" * 64


def _settings(child=350, parent=2000, max_embed=8000):
    return RetrievalSettings(
        child_chunk_tokens=child, parent_chunk_tokens=parent, max_embed_chars=max_embed
    )


def _narrative_doc(doc_key="SOP-004"):
    meta = DocMeta(
        doc_key=doc_key,
        doc_type="sop",
        title="Corrective and Preventive Action",
        revision="C",
        file_format="docx",
    )
    blocks = (
        ParsedBlock(kind="heading", text="SOP-004 — CAPA", heading_level=1),
        ParsedBlock(kind="paragraph", text="Purpose statement for the procedure."),
        ParsedBlock(kind="heading", text="1. Scope", heading_level=2, section_path="1. Scope"),
        ParsedBlock(
            kind="paragraph", text="Applies to all quality records.", section_path="1. Scope"
        ),
        ParsedBlock(
            kind="heading", text="2. Procedure", heading_level=2, section_path="2. Procedure"
        ),
        ParsedBlock(
            kind="paragraph", text="Open a CAPA within five days.", section_path="2. Procedure"
        ),
    )
    return ParsedDocument(meta=meta, blocks=blocks, parser="docx_narrative")


def test_narrative_sections_become_parent_child_pairs():
    chunks = chunk_document(_narrative_doc(), content_hash=HASH_A, settings=_settings())
    parents = [c for c in chunks if c.chunk_type == "parent"]
    children = [c for c in chunks if c.chunk_type == "child"]
    # header preamble + Scope + Procedure
    assert len(parents) == 3
    assert children
    parent_ids = {p.chunk_id for p in parents}
    assert all(c.parent_id in parent_ids for c in children)
    section_paths = {p.section_path for p in parents}
    assert "1. Scope" in section_paths
    assert "2. Procedure" in section_paths


def test_ordinals_sequential_and_ids_stable():
    chunks = chunk_document(_narrative_doc(), content_hash=HASH_A, settings=_settings())
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    again = chunk_document(_narrative_doc(), content_hash=HASH_A, settings=_settings())
    assert [c.chunk_id for c in chunks] == [c.chunk_id for c in again]
    other = chunk_document(_narrative_doc(), content_hash=HASH_B, settings=_settings())
    assert set(c.chunk_id for c in chunks).isdisjoint(c.chunk_id for c in other)
    for c in chunks:
        uuid.UUID(c.chunk_id)


def test_same_bytes_under_different_doc_keys_get_disjoint_ids():
    # Two controlled documents that happen to share identical bytes (a shared
    # boilerplate form, an empty template) must not collide on chunk id — the
    # chunks PK and the Qdrant point id are seeded on doc_key as well as hash.
    one = chunk_document(_narrative_doc("SOP-004"), content_hash=HASH_A, settings=_settings())
    two = chunk_document(_narrative_doc("SOP-999"), content_hash=HASH_A, settings=_settings())
    assert set(c.chunk_id for c in one).isdisjoint(c.chunk_id for c in two)
    # Same shape, so the only difference is identity, not structure.
    assert [c.ordinal for c in one] == [c.ordinal for c in two]
    assert [c.chunk_type for c in one] == [c.chunk_type for c in two]


def test_context_header_prepended_via_embed_text():
    chunks = chunk_document(_narrative_doc(), content_hash=HASH_A, settings=_settings())
    child = next(c for c in chunks if c.chunk_type == "child")
    assert child.context_header == ("SOP-004 Rev C — Corrective and Preventive Action (sop)")
    assert child.embed_text.startswith(child.context_header)
    assert child.text in child.embed_text


def test_row_document_batches_rows_into_parents():
    meta = DocMeta(doc_key="TM-100", doc_type="trace_matrix", title="Trace Matrix", revision="B")
    blocks = tuple(
        ParsedBlock(
            kind="row",
            text=f"Requirement ID: REQ-{n:03d} | Description: requirement text {n} " + "word " * 20,
            section_path=f"trace_matrix row REQ-{n:03d}",
            fields={"Requirement ID": f"REQ-{n:03d}"},
            row_number=n + 3,
        )
        for n in range(1, 21)
    )
    parsed = ParsedDocument(
        meta=meta, blocks=blocks, parser="xlsx_matrix", attributes={"template": "trace_matrix"}
    )
    chunks = chunk_document(parsed, content_hash=HASH_A, settings=_settings(parent=100))
    parents = [c for c in chunks if c.chunk_type == "parent"]
    rows = [c for c in chunks if c.chunk_type == "row"]
    assert len(parents) > 1
    assert len(rows) == 20
    assert all(r.parent_id for r in rows)
    assert rows[0].payload["fields"]["Requirement ID"] == "REQ-001"
    assert rows[0].payload["row_number"] == 4
    multi = next(p for p in parents if ".." in p.section_path)
    assert "part" in multi.section_path


def test_fmea_banner_in_context_header():
    meta = DocMeta(doc_key="DFMEA-100", doc_type="dfmea", title="Design FMEA", revision="A")
    blocks = (
        ParsedBlock(
            kind="row",
            text="#: 12 | Failure Mode: seal leak | S: 9 | O: 3 | D: 4 | AP: H",
            section_path="fmea row 12",
            fields={"#": "12"},
            row_number=5,
        ),
    )
    parsed = ParsedDocument(
        meta=meta, blocks=blocks, parser="xlsx_matrix", attributes={"template": "fmea"}
    )
    chunks = chunk_document(parsed, content_hash=HASH_A, settings=_settings())
    assert "Action Priority" in chunks[0].context_header


def test_page_document_one_chunk_per_page():
    meta = DocMeta(doc_key="C-2025-0142", doc_type="complaint", title="Complaint")
    blocks = tuple(
        ParsedBlock(kind="page", text=f"Complaint page {n} content " + "word " * 30, page=n)
        for n in (1, 2)
    )
    parsed = ParsedDocument(meta=meta, blocks=blocks, parser="pdf_form")
    chunks = chunk_document(parsed, content_hash=HASH_A, settings=_settings())
    pages = [c for c in chunks if c.chunk_type == "page"]
    assert [p.page for p in pages] == [1, 2]
    assert all(p.parent_id for p in pages)


def test_children_pack_on_block_boundaries():
    meta = DocMeta(doc_key="SOP-011", doc_type="sop", title="Blocks", revision="A")
    para_a = "alpha " * 200
    para_b = "bravo " * 200
    blocks = (
        ParsedBlock(kind="paragraph", text=para_a.strip()),
        ParsedBlock(kind="paragraph", text=para_b.strip()),
    )
    parsed = ParsedDocument(meta=meta, blocks=blocks, parser="docx_narrative")
    chunks = chunk_document(parsed, content_hash=HASH_A, settings=_settings(child=350, parent=2000))
    children = [c for c in chunks if c.chunk_type == "child"]
    # 200 + 200 > 350: each paragraph becomes its own child, never a mixed
    # 350-word window followed by a 50-word remainder
    assert [c.text for c in children] == [para_a.strip(), para_b.strip()]
    parent = next(c for c in chunks if c.chunk_type == "parent")
    assert parent.text == f"{para_a.strip()}\n{para_b.strip()}"


def test_oversized_block_split_on_word_boundary():
    meta = DocMeta(doc_key="SOP-010", doc_type="sop", title="Long", revision="A")
    long_text = "word " * 900
    blocks = (ParsedBlock(kind="paragraph", text=long_text.strip()),)
    parsed = ParsedDocument(meta=meta, blocks=blocks, parser="docx_narrative")
    chunks = chunk_document(parsed, content_hash=HASH_A, settings=_settings(child=350, parent=2000))
    children = [c for c in chunks if c.chunk_type == "child"]
    assert len(children) == 3
    assert all(c.token_count <= 350 for c in children)
    reassembled = " ".join(c.text for c in children)
    assert reassembled == long_text.strip()


def test_child_embed_text_respects_char_ceiling_including_header():
    # A child small in token count can still be large in characters (dense
    # identifiers, punctuation). The character ceiling bounds embed_text — header
    # included — so the embedding model can never silently truncate a child.
    meta = DocMeta(doc_key="SOP-010", doc_type="sop", title="Long", revision="A")
    blocks = (ParsedBlock(kind="paragraph", text="word " * 60),)  # ~60 tokens, ~300 chars
    parsed = ParsedDocument(meta=meta, blocks=blocks, parser="docx_narrative")
    ceiling = 120
    chunks = chunk_document(parsed, content_hash=HASH_A, settings=_settings(max_embed=ceiling))
    children = [c for c in chunks if c.chunk_type == "child"]
    assert len(children) > 1
    assert all(len(c.embed_text) <= ceiling for c in children)
    assert all(c.token_count == len(c.text.split()) for c in children)


def test_oversized_row_is_split_to_fit_ceiling():
    # A single spreadsheet row longer than the ceiling must be split into several
    # row children rather than emitted whole and truncated at embedding time.
    meta = DocMeta(doc_key="TM-100", doc_type="trace_matrix", title="Trace Matrix", revision="B")
    big_row = "Requirement ID: REQ-001 | Description: " + "detail " * 200
    blocks = (
        ParsedBlock(
            kind="row",
            text=big_row.strip(),
            section_path="trace_matrix row REQ-001",
            fields={"Requirement ID": "REQ-001"},
            row_number=4,
        ),
    )
    parsed = ParsedDocument(
        meta=meta, blocks=blocks, parser="xlsx_matrix", attributes={"template": "trace_matrix"}
    )
    ceiling = 200
    chunks = chunk_document(parsed, content_hash=HASH_A, settings=_settings(max_embed=ceiling))
    rows = [c for c in chunks if c.chunk_type == "row"]
    assert len(rows) > 1
    assert all(len(c.embed_text) <= ceiling for c in rows)
    assert all(c.parent_id for c in rows)
    assert all(c.payload["fields"]["Requirement ID"] == "REQ-001" for c in rows)


def test_default_ceiling_leaves_normal_rows_intact():
    # The default ceiling is generous enough that ordinary rows are never
    # fragmented — one row in, one row child out.
    meta = DocMeta(doc_key="TM-100", doc_type="trace_matrix", title="Trace Matrix", revision="B")
    blocks = tuple(
        ParsedBlock(
            kind="row",
            text=f"Requirement ID: REQ-{n:03d} | Description: requirement text {n}",
            section_path=f"trace_matrix row REQ-{n:03d}",
            fields={"Requirement ID": f"REQ-{n:03d}"},
            row_number=n + 3,
        )
        for n in range(1, 6)
    )
    parsed = ParsedDocument(
        meta=meta, blocks=blocks, parser="xlsx_matrix", attributes={"template": "trace_matrix"}
    )
    chunks = chunk_document(parsed, content_hash=HASH_A, settings=_settings())
    rows = [c for c in chunks if c.chunk_type == "row"]
    assert len(rows) == 5
