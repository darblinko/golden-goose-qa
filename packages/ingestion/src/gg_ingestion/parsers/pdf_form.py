"""Born-digital PDF parser (pypdf text extraction, page-level provenance).

QMS record forms (NCR, complaint, MDR, verification report, DHR traveler) are
single- or few-page born-digital PDFs; page text is enough for retrieval and
citation at page granularity. Scanned PDFs (no text layer) raise
NoTextLayerError so the pipeline retries them via the OCR parser — a scan must
never be silently ingested as an empty document.
"""

from pathlib import Path

from pypdf import PdfReader

from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument
from gg_ingestion.parsers.base import DocumentParser, NoTextLayerError, ParseError

_MIN_TEXT_CHARS_PER_PAGE = 40


class PdfFormParser(DocumentParser):
    name = "pdf_form"

    def parse(self, path: Path, meta: DocMeta) -> ParsedDocument:
        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            raise ParseError(f"cannot open pdf {path.name}: {exc}") from exc

        blocks: list[ParsedBlock] = []
        empty_pages: list[int] = []
        total_pages = len(reader.pages)
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if len(text) < _MIN_TEXT_CHARS_PER_PAGE:
                empty_pages.append(page_number)
                continue
            blocks.append(ParsedBlock(kind="page", text=text, page=page_number))

        if not blocks:
            raise NoTextLayerError(
                f"pdf {path.name} has no usable text layer "
                f"({len(empty_pages)} empty pages); scanned documents require the OCR path"
            )
        warnings = tuple(f"page {n} below text-layer threshold, skipped" for n in empty_pages)
        # Below-threshold pages are left for the pipeline's per-page OCR recovery;
        # pdf_pages lets that final coverage check confirm every physical page was
        # ultimately recovered rather than silently dropped.
        return ParsedDocument(
            meta=meta,
            blocks=tuple(blocks),
            parser=self.name,
            warnings=warnings,
            attributes={"pdf_pages": str(total_pages)},
        )
