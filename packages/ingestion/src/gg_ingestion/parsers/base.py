"""Parser seam. Concrete parsers stay swappable behind this interface so a
heavier layout-analysis engine (Docling) can replace a native parser without
touching the pipeline (ADR-0011)."""

from abc import ABC, abstractmethod
from pathlib import Path

from gg_ingestion.models import DocMeta, ParsedDocument


class ParseError(RuntimeError):
    """Raised when a file cannot be parsed. Never swallowed: the pipeline
    records it as a failed document, queryable as failed."""


class NoTextLayerError(ParseError):
    """A born-digital parser met a PDF with no extractable text layer. The
    pipeline treats this as a routing signal — retry via the OCR parser —
    rather than a terminal failure."""


class DocumentParser(ABC):
    name: str

    @abstractmethod
    def parse(self, path: Path, meta: DocMeta) -> ParsedDocument: ...


class AsyncDocumentParser(ABC):
    """Parsers whose work awaits an external provider (OCR). Same contract as
    DocumentParser; the pipeline dispatches on which base class a route's
    parser implements."""

    name: str

    @abstractmethod
    async def parse(self, path: Path, meta: DocMeta) -> ParsedDocument: ...
