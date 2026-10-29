"""Excel grid parser: person-per-row, document-per-column matrices.

The training matrix is a grid, not a record list — the header row is
("Employee", <doc key>, <doc key>, ...) with a variable column set, so it
cannot be fingerprinted by a fixed template. Each employee row becomes one
block whose fields map document keys to that person's training entry
("Rev B 14-Mar-2025"), which is exactly what the trace extractors and the
training register need.
"""

import re
from pathlib import Path

from openpyxl import load_workbook

from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument
from gg_ingestion.parsers.base import DocumentParser, ParseError
from gg_ingestion.parsers.xlsx_matrix import assert_single_sheet, preamble_attributes

_MAX_HEADER_SCAN_ROWS = 10
_DOC_COLUMN_RE = re.compile(r"^[A-Z]{2,6}-[0-9]{2,4}$")


class XlsxGridParser(DocumentParser):
    name = "xlsx_grid"

    def parse(self, path: Path, meta: DocMeta) -> ParsedDocument:
        try:
            wb = load_workbook(str(path), data_only=True)
        except Exception as exc:
            raise ParseError(f"cannot open xlsx {path.name}: {exc}") from exc
        assert_single_sheet(wb, path.name)
        ws = wb.active
        if ws is None:
            raise ParseError(f"xlsx {path.name} has no active worksheet")

        grid = [
            tuple("" if v is None else str(v).strip() for v in row)
            for row in ws.iter_rows(values_only=True)
        ]
        header_idx = self._find_header(grid, path.name)
        header = grid[header_idx - 1]
        # Keep each document column at its true position. Compressing out blank
        # header cells and then zipping against raw row cells shifts completion
        # values onto the wrong controlled-document column — a confidently wrong
        # training record.
        doc_columns = [(col_idx, key) for col_idx, key in enumerate(header) if col_idx >= 1 and key]
        doc_keys = [key for _, key in doc_columns]

        attributes = preamble_attributes(grid[: header_idx - 1])
        blocks: list[ParsedBlock] = []
        for row_idx, row in enumerate(grid[header_idx:], start=header_idx + 1):
            person = row[0] if row else ""
            if not person:
                continue
            fields = {"Employee": person}
            fields.update(
                {
                    key: row[col_idx]
                    for col_idx, key in doc_columns
                    if col_idx < len(row) and row[col_idx]
                }
            )
            entries = " | ".join(f"{k}: {v}" for k, v in fields.items() if k != "Employee")
            blocks.append(
                ParsedBlock(
                    kind="row",
                    text=f"Employee: {person} | {entries}" if entries else f"Employee: {person}",
                    section_path=f"training row {person}",
                    fields=fields,
                    row_number=row_idx,
                )
            )
        if not blocks:
            raise ParseError(f"xlsx {path.name} training grid has no employee rows")

        title = attributes.get("title", meta.title)
        if title.startswith(meta.doc_key):
            title = title.removeprefix(meta.doc_key).strip() or meta.title
        enriched = DocMeta(
            doc_key=meta.doc_key,
            doc_type=meta.doc_type,
            title=title,
            revision=attributes.get("revision"),
            file_format=meta.file_format,
        )
        attributes["template"] = "training_grid"
        attributes["doc_columns"] = ", ".join(doc_keys)
        return ParsedDocument(
            meta=enriched, blocks=tuple(blocks), parser=self.name, attributes=attributes
        )

    def _find_header(self, grid: list[tuple[str, ...]], filename: str) -> int:
        for row_idx, row in enumerate(grid[:_MAX_HEADER_SCAN_ROWS], start=1):
            if not row or row[0] != "Employee":
                continue
            doc_cells = [c for c in row[1:] if c]
            if doc_cells and all(_DOC_COLUMN_RE.match(c) for c in doc_cells):
                return row_idx
        raise ParseError(
            f"xlsx {filename} is not a training grid: no 'Employee' header row with "
            f"document-key columns in the first {_MAX_HEADER_SCAN_ROWS} rows"
        )
