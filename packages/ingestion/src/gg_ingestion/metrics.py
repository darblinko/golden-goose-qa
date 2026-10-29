"""Per-document ingestion metrics and hard QA gates.

Errors are data: a document that fails a gate is recorded as failed with the
gate name — never quietly dropped, never padded with a plausible default.
"""

import math
from dataclasses import asdict, dataclass

from gg_ingestion.models import Chunk, ParsedDocument

_MIN_TEXT_COVERAGE = 0.75
_MIN_OCR_CONFIDENCE = 0.6


class IngestGateError(RuntimeError):
    def __init__(self, gate: str, detail: str) -> None:
        self.gate = gate
        super().__init__(f"gate '{gate}' failed: {detail}")


@dataclass(frozen=True)
class DocumentMetrics:
    parser: str
    n_blocks: int
    n_chunks: int
    n_children: int
    n_parents: int
    text_coverage: float
    sanitize_hits: int
    parse_warnings: tuple[str, ...]
    seconds: float
    ocr_min_confidence: float | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def compute_metrics(
    parsed: ParsedDocument,
    chunks: list[Chunk],
    *,
    sanitize_hits: int,
    seconds: float,
) -> DocumentMetrics:
    children = [c for c in chunks if c.chunk_type != "parent"]
    parents = [c for c in chunks if c.chunk_type == "parent"]
    source_chars = sum(len(b.text) for b in parsed.blocks)
    child_chars = sum(len(c.text) for c in children)
    coverage = (child_chars / source_chars) if source_chars else 0.0
    ocr_confidence = parsed.attributes.get("ocr_min_confidence")
    return DocumentMetrics(
        parser=parsed.parser,
        n_blocks=len(parsed.blocks),
        n_chunks=len(chunks),
        n_children=len(children),
        n_parents=len(parents),
        text_coverage=round(coverage, 4),
        sanitize_hits=sanitize_hits,
        parse_warnings=parsed.warnings,
        seconds=round(seconds, 3),
        ocr_min_confidence=float(ocr_confidence) if ocr_confidence is not None else None,
    )


def enforce_gates(metrics: DocumentMetrics) -> None:
    # A controlled document that carries prompt-injection / instruction-like text
    # is treated as tampered at the source: redaction neutralized it in place, but
    # indexing the sanitized bytes would still publish a compromised record as
    # trusted evidence. Any hit quarantines the document as failed. Checked first
    # so a poisoned document is flagged as such regardless of its other metrics.
    if metrics.sanitize_hits > 0:
        raise IngestGateError(
            "prompt_injection",
            f"{metrics.sanitize_hits} instruction-like pattern(s) neutralized in "
            "extracted text; a controlled document must not carry them — quarantined "
            "rather than indexed",
        )
    if metrics.n_children == 0:
        raise IngestGateError("zero_chunks", "document produced no child chunks")
    if metrics.text_coverage < _MIN_TEXT_COVERAGE:
        raise IngestGateError(
            "text_coverage",
            f"{metrics.text_coverage:.2%} of parsed text reached chunks "
            f"(floor {_MIN_TEXT_COVERAGE:.0%})",
        )
    if metrics.ocr_min_confidence is not None and not (
        math.isfinite(metrics.ocr_min_confidence)
        and metrics.ocr_min_confidence >= _MIN_OCR_CONFIDENCE
    ):
        raise IngestGateError(
            "ocr_confidence",
            f"lowest page OCR confidence {metrics.ocr_min_confidence:.2f} "
            f"below floor {_MIN_OCR_CONFIDENCE:.2f}; degraded scan must not be indexed",
        )
