"""Routes a file to its parser by document class.

Scanned device history records route to the OCR parser directly; any other
PDF that turns out to have no text layer reaches the same parser via the
pipeline's NoTextLayerError fallback. Files with no parsing path at all are
classified as skipped — an explicit, queryable outcome, never a silent drop.
"""

from dataclasses import dataclass
from pathlib import Path

from gg_common.providers.base import OCRProvider

from gg_ingestion.docmeta import doc_meta_from_path
from gg_ingestion.models import DocMeta
from gg_ingestion.parsers.base import AsyncDocumentParser, DocumentParser
from gg_ingestion.parsers.docx_narrative import DocxNarrativeParser
from gg_ingestion.parsers.pdf_form import PdfFormParser
from gg_ingestion.parsers.pdf_scanned import ScannedPdfParser
from gg_ingestion.parsers.xlsx_grid import XlsxGridParser
from gg_ingestion.parsers.xlsx_matrix import XlsxMatrixParser
from gg_ingestion.parsers.xml_form import XmlFormParser


@dataclass(frozen=True)
class Route:
    meta: DocMeta
    parser: DocumentParser | AsyncDocumentParser | None
    skip_reason: str | None = None


class ParserRouter:
    def __init__(self, *, ocr: OCRProvider) -> None:
        self._docx = DocxNarrativeParser()
        self._pdf = PdfFormParser()
        self._xlsx = XlsxMatrixParser()
        self._grid = XlsxGridParser()
        self._xml = XmlFormParser()
        self.scanned = ScannedPdfParser(ocr)

    def route(self, path: Path) -> Route:
        meta = doc_meta_from_path(path)
        if meta.doc_type == "dhr_scanned":
            return Route(meta=meta, parser=self.scanned)
        if meta.doc_type == "training_matrix":
            return Route(meta=meta, parser=self._grid)
        parser: DocumentParser | None = {
            "docx": self._docx,
            "pdf": self._pdf,
            "xlsx": self._xlsx,
            "xml": self._xml,
        }.get(meta.file_format)
        if parser is None:
            return Route(meta=meta, parser=None, skip_reason=f"no parser for .{meta.file_format}")
        return Route(meta=meta, parser=parser)
