"""Provenance guard for the BM25 average-document-length constant.

ADR-0012 pins gg_common.sparse._AVG_DOC_LEN to the mean child-chunk length over
the seeded corpus. This recomputes that mean from the generated corpus exactly
as ingestion tokenizes it, and fails if the shipped constant has drifted — so
the value can never silently regress to an unjustified magic number.
"""

import hashlib
import statistics
from pathlib import Path

from gg_common.providers import FakeOCRProvider
from gg_common.settings import RetrievalSettings
from gg_common.sparse import _AVG_DOC_LEN, tokenize
from gg_ingestion.chunking import chunk_document
from gg_ingestion.parsers.base import DocumentParser
from gg_ingestion.parsers.router import ParserRouter


def _corpus_mean_child_len(corpus_dir: Path) -> float:
    settings = RetrievalSettings()
    router = ParserRouter(ocr=FakeOCRProvider())  # scanned PDFs skipped below; OCR unused
    lengths: list[int] = []
    for path in sorted(corpus_dir.rglob("*")):
        if not path.is_file():
            continue
        route = router.route(path)
        # Only the synchronous parsers; the 3 OCR-only scanned PDFs are excluded
        # (they route to the async parser) and are a negligible share of chunks.
        if not isinstance(route.parser, DocumentParser):
            continue
        parsed = route.parser.parse(path, route.meta)
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        for chunk in chunk_document(parsed, content_hash=content_hash, settings=settings):
            if chunk.chunk_type == "child":
                lengths.append(len(tokenize(chunk.embed_text)))
    assert lengths, "no child chunks measured from the corpus"
    return statistics.mean(lengths)


def test_avg_doc_len_tracks_corpus_mean(corpus_dir):
    measured = _corpus_mean_child_len(corpus_dir)
    drift = abs(measured - _AVG_DOC_LEN) / _AVG_DOC_LEN
    assert drift < 0.10, (
        f"corpus mean child-chunk length {measured:.1f} has drifted "
        f"{drift:.0%} from _AVG_DOC_LEN={_AVG_DOC_LEN}; re-derive the constant "
        f"and update ADR-0012"
    )
