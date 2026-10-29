import pytest
from gg_ingestion.metrics import IngestGateError, compute_metrics, enforce_gates
from gg_ingestion.models import Chunk, DocMeta, ParsedBlock, ParsedDocument


def _doc(blocks):
    meta = DocMeta(doc_key="SOP-001", doc_type="sop", title="Test")
    return ParsedDocument(meta=meta, blocks=tuple(blocks), parser="docx_narrative")


def _chunk(chunk_type, text, ordinal=0):
    return Chunk(
        chunk_id=f"id-{ordinal}",
        ordinal=ordinal,
        chunk_type=chunk_type,
        section_path="",
        text=text,
        context_header="",
        token_count=len(text.split()),
    )


def test_full_coverage_passes():
    text = "The quick brown fox jumps over the lazy dog."
    parsed = _doc([ParsedBlock(kind="paragraph", text=text)])
    chunks = [_chunk("parent", text, 0), _chunk("child", text, 1)]
    metrics = compute_metrics(parsed, chunks, sanitize_hits=0, seconds=0.1)
    assert metrics.text_coverage == 1.0
    assert metrics.n_children == 1
    assert metrics.n_parents == 1
    enforce_gates(metrics)


def test_sanitize_hit_is_a_hard_gate():
    # A controlled document must not carry instruction-like text. Redaction alone
    # still indexes tampered bytes, so any sanitize hit quarantines the document
    # as failed rather than publishing it as trusted evidence.
    text = "The quick brown fox jumps over the lazy dog."
    parsed = _doc([ParsedBlock(kind="paragraph", text=text)])
    chunks = [_chunk("parent", text, 0), _chunk("child", text, 1)]
    metrics = compute_metrics(parsed, chunks, sanitize_hits=2, seconds=0.1)
    with pytest.raises(IngestGateError) as exc:
        enforce_gates(metrics)
    assert exc.value.gate == "prompt_injection"
    # The hit count is surfaced so the failed row records how many patterns fired.
    assert "2" in str(exc.value)


def test_zero_chunks_gate():
    parsed = _doc([ParsedBlock(kind="paragraph", text="content here")])
    metrics = compute_metrics(parsed, [], sanitize_hits=0, seconds=0.0)
    with pytest.raises(IngestGateError) as exc:
        enforce_gates(metrics)
    assert exc.value.gate == "zero_chunks"


def test_low_coverage_gate():
    parsed = _doc([ParsedBlock(kind="paragraph", text="x" * 1000)])
    chunks = [_chunk("parent", "x" * 100, 0), _chunk("child", "x" * 100, 1)]
    metrics = compute_metrics(parsed, chunks, sanitize_hits=0, seconds=0.0)
    with pytest.raises(IngestGateError) as exc:
        enforce_gates(metrics)
    assert exc.value.gate == "text_coverage"


def _scanned_doc(min_confidence):
    return ParsedDocument(
        meta=DocMeta(doc_key="DHR-L250007", doc_type="dhr_scanned", title="Test"),
        blocks=(ParsedBlock(kind="page", text="FAKE_OCR_PAGE:abc123", page=1),),
        parser="pdf_scanned",
        attributes={"ocr_pages": "1", "ocr_min_confidence": f"{min_confidence:.4f}"},
    )


def test_ocr_confidence_gate_blocks_degraded_scan():
    text = "FAKE_OCR_PAGE:abc123"
    chunks = [_chunk("parent", text, 0), _chunk("page", text, 1)]
    metrics = compute_metrics(_scanned_doc(0.4), chunks, sanitize_hits=0, seconds=0.0)
    assert metrics.ocr_min_confidence == 0.4
    with pytest.raises(IngestGateError) as exc:
        enforce_gates(metrics)
    assert exc.value.gate == "ocr_confidence"


def test_ocr_confidence_above_floor_passes():
    text = "FAKE_OCR_PAGE:abc123"
    chunks = [_chunk("parent", text, 0), _chunk("page", text, 1)]
    metrics = compute_metrics(_scanned_doc(0.95), chunks, sanitize_hits=0, seconds=0.0)
    enforce_gates(metrics)


def test_ocr_confidence_nan_fails_gate():
    text = "FAKE_OCR_PAGE:abc123"
    chunks = [_chunk("parent", text, 0), _chunk("page", text, 1)]
    metrics = compute_metrics(_scanned_doc(float("nan")), chunks, sanitize_hits=0, seconds=0.0)
    with pytest.raises(IngestGateError) as exc:
        enforce_gates(metrics)
    assert exc.value.gate == "ocr_confidence"


def test_as_dict_round_trips_warnings():
    parsed = ParsedDocument(
        meta=DocMeta(doc_key="SOP-001", doc_type="sop", title="Test"),
        blocks=(ParsedBlock(kind="paragraph", text="body"),),
        parser="docx_narrative",
        warnings=("no revision attribute extracted",),
    )
    metrics = compute_metrics(parsed, [_chunk("child", "body")], sanitize_hits=2, seconds=1.234)
    data = metrics.as_dict()
    assert data["sanitize_hits"] == 2
    assert data["parse_warnings"] == ("no revision attribute extracted",)
    assert data["seconds"] == 1.234
