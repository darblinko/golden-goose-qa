"""Scanned PDF parser: embedded page images through the OCR provider.

Scanner output embeds one raster image per page; pypdf hands the encoded bytes
back without re-rendering, so no rasterizer dependency is needed. Pages are
OCR'd concurrently (bounded), each page retried once on provider error. The
lowest page confidence is recorded in the document attributes so the ingestion
confidence gate can block a degraded scan — a page the OCR could not read is a
real evidence gap and must fail loudly, never index as garbage text.

The same OCR path also recovers the image-only pages of a *hybrid* PDF, whose
born-digital pages carry a text layer while inserted scans do not: the pipeline
asks ocr_selected_pages to read exactly the pages the born-digital parser could
not, so those pages are OCR'd rather than silently dropped.
"""

import asyncio
from pathlib import Path

from gg_common.costs import cost_stage
from gg_common.providers.base import OCRPage, OCRProvider
from pypdf import PdfReader

from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument
from gg_ingestion.parsers.base import AsyncDocumentParser, ParseError

_MAX_CONCURRENT_PAGES = 4


class ScannedPdfParser(AsyncDocumentParser):
    name = "pdf_scanned"

    def __init__(self, ocr: OCRProvider) -> None:
        self._ocr = ocr

    async def parse(self, path: Path, meta: DocMeta) -> ParsedDocument:
        reader = self._open(path)
        page_images = self._collect_page_images(reader)
        if not page_images:
            raise ParseError(
                f"pdf {path.name} has no embedded page images; nothing for the OCR path to read"
            )
        blocks, confidences, warnings = await self._ocr_page_images(path.name, page_images)
        imageless = len(reader.pages) - len(page_images)
        if imageless:
            warnings.append(f"{imageless} pages had no embedded image and produced no text")
        return ParsedDocument(
            meta=meta,
            blocks=tuple(blocks),
            parser=self.name,
            warnings=tuple(warnings),
            attributes=_ocr_attributes(len(reader.pages), len(page_images), confidences),
        )

    async def ocr_selected_pages(
        self, path: Path, meta: DocMeta, *, exclude_pages: set[int]
    ) -> ParsedDocument | None:
        """OCR every image-bearing page whose number is not in exclude_pages.

        For hybrid PDFs: the born-digital parser passes the page numbers it
        already extracted as text, and this reads exactly the remaining
        image-only pages. Returns None when no such page carries an image, so
        the caller leaves a purely born-digital document untouched.
        """
        reader = self._open(path)
        page_images = [
            (n, images) for n, images in self._collect_page_images(reader) if n not in exclude_pages
        ]
        if not page_images:
            return None
        blocks, confidences, warnings = await self._ocr_page_images(path.name, page_images)
        return ParsedDocument(
            meta=meta,
            blocks=tuple(blocks),
            parser=self.name,
            warnings=tuple(warnings),
            attributes=_ocr_attributes(len(reader.pages), len(page_images), confidences),
        )

    def _open(self, path: Path) -> PdfReader:
        try:
            return PdfReader(str(path))
        except Exception as exc:
            raise ParseError(f"cannot open pdf {path.name}: {exc}") from exc

    def _collect_page_images(self, reader: PdfReader) -> list[tuple[int, list[bytes]]]:
        page_images: list[tuple[int, list[bytes]]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            images = [img.data for img in page.images]
            if images:
                page_images.append((page_number, images))
        return page_images

    async def _ocr_page_images(
        self, file_name: str, page_images: list[tuple[int, list[bytes]]]
    ) -> tuple[list[ParsedBlock], list[float], list[str]]:
        # Created per call: a semaphore binds to the running event loop, and
        # the parser instance outlives any single loop.
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PAGES)
        results = await asyncio.gather(
            *(self._ocr_page(semaphore, file_name, n, images) for n, images in page_images)
        )
        blocks: list[ParsedBlock] = []
        confidences: list[float] = []
        warnings: list[str] = []
        for page_number, pages in results:
            text = "\n".join(p.text for p in pages if p.text.strip())
            blocks.append(ParsedBlock(kind="page", text=text, page=page_number))
            confidences.extend(p.confidence for p in pages)
            warnings.extend(w for p in pages for w in p.warnings)
        return blocks, confidences, warnings

    async def _ocr_page(
        self, semaphore: asyncio.Semaphore, file_name: str, page_number: int, images: list[bytes]
    ) -> tuple[int, list[OCRPage]]:
        async with semaphore:
            return page_number, [
                await self._ocr_image(file_name, page_number, image) for image in images
            ]

    async def _ocr_image(self, file_name: str, page_number: int, image: bytes) -> OCRPage:
        try:
            with cost_stage("ingest.ocr"):
                return await self._ocr.ocr_page(image, page_number=page_number)
        except Exception:
            try:
                with cost_stage("ingest.ocr"):
                    return await self._ocr.ocr_page(image, page_number=page_number)
            except Exception as exc:
                raise ParseError(
                    f"ocr failed for {file_name} page {page_number} after retry: {exc}"
                ) from exc


def _ocr_attributes(total_pages: int, ocr_pages: int, confidences: list[float]) -> dict[str, str]:
    return {
        "pdf_pages": str(total_pages),
        "ocr_pages": str(ocr_pages),
        "ocr_min_confidence": f"{min(confidences):.4f}",
    }
