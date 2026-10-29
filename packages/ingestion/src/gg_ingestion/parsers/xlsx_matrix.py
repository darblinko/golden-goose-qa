"""Excel matrix parser: row-as-record with template fingerprinting.

Matrices (trace matrix, DFMEA/PFMEA) are parsed natively with openpyxl so each
worksheet row survives as one record — the unit an auditor asks about. A
template is fingerprinted by its header row; merged cells are forward-filled
from the merge anchor; rows above the header (title band, AIAG-VDA group band)
become document attributes, not noise.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument
from gg_ingestion.parsers.base import DocumentParser, ParseError

_MAX_HEADER_SCAN_ROWS = 10


def assert_single_sheet(wb: Workbook, filename: str) -> None:
    """Both spreadsheet parsers read only the active sheet, so a second sheet
    would be silently ignored — potentially an entire controlled-document column
    or record set. A corpus workbook is expected to hold exactly one worksheet;
    fail loudly rather than parse a partial workbook."""
    sheets = wb.worksheets
    if len(sheets) > 1:
        names = ", ".join(sheet.title for sheet in sheets)
        raise ParseError(
            f"xlsx {filename} has {len(sheets)} worksheets ({names}); only single-sheet "
            f"workbooks are supported so no sheet's records are silently ignored"
        )


_REVISION_LINE_RE = re.compile(
    r"Revision\s+(?P<rev>[A-Z])\s+—\s+Effective\s+(?P<date>[0-9]{2}-[A-Za-z]{3}-[0-9]{4})"
    r"\s+—\s+Approved by\s+(?P<approver>.+)"
)


@dataclass(frozen=True)
class MatrixTemplate:
    name: str
    header: tuple[str, ...]
    key_column: str


TEMPLATES: tuple[MatrixTemplate, ...] = (
    MatrixTemplate(
        name="trace_matrix",
        header=(
            "Requirement ID",
            "Category",
            "Requirement Text",
            "Design Output(s)",
            "Verification Protocol",
            "Verification Report",
            "Result",
            "Completed",
        ),
        key_column="Requirement ID",
    ),
    MatrixTemplate(
        name="fmea",
        header=(
            "#",
            "Item",
            "Function",
            "Failure Mode",
            "Effect",
            "S",
            "Potential Cause",
            "O",
            "Prevention Control",
            "Detection Control",
            "D",
            "AP",
            "Risk File Ref",
            "DFMEA Ref",
        ),
        key_column="#",
    ),
    MatrixTemplate(
        name="control_plan",
        header=(
            "#",
            "Process Step",
            "PFMEA Ref",
            "Characteristic",
            "Specification",
            "Control Method",
            "Frequency",
            "Reference",
            "Reaction Plan",
        ),
        key_column="#",
    ),
    MatrixTemplate(
        name="supplier_list",
        header=(
            "Supplier ID",
            "Supplier Name",
            "Commodity",
            "Approval Status",
            "Last Audit",
            "Audit Report",
        ),
        key_column="Supplier ID",
    ),
)


def _forward_fill_merges(ws: Worksheet) -> dict[tuple[int, int], object]:
    """Values for merged cells, keyed by (row, col), taken from the anchor."""
    filled: dict[tuple[int, int], object] = {}
    for merged in ws.merged_cells.ranges:
        anchor = ws.cell(row=merged.min_row, column=merged.min_col).value
        for row in range(merged.min_row, merged.max_row + 1):
            for col in range(merged.min_col, merged.max_col + 1):
                filled[(row, col)] = anchor
    return filled


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


class XlsxMatrixParser(DocumentParser):
    name = "xlsx_matrix"

    def parse(self, path: Path, meta: DocMeta) -> ParsedDocument:
        try:
            wb = load_workbook(str(path), data_only=True)
        except Exception as exc:
            raise ParseError(f"cannot open xlsx {path.name}: {exc}") from exc

        assert_single_sheet(wb, path.name)
        ws = wb.active
        if ws is None:
            raise ParseError(f"xlsx {path.name} has no active worksheet")

        merges = _forward_fill_merges(ws)
        grid: list[tuple[str, ...]] = []
        for row_idx, row in enumerate(ws.iter_rows(values_only=False), start=1):
            values = []
            for col_idx, cell in enumerate(row, start=1):
                value = merges.get((row_idx, col_idx), cell.value)
                values.append(_cell_text(value))
            grid.append(tuple(values))

        template, header_row_idx = self._fingerprint(grid, path.name)
        attributes = self._preamble_attributes(grid[: header_row_idx - 1])
        header = grid[header_row_idx - 1][: len(template.header)]

        blocks: list[ParsedBlock] = []
        key_pos = header.index(template.key_column)
        for row_idx, row_values in enumerate(grid[header_row_idx:], start=header_row_idx + 1):
            trimmed = row_values[: len(template.header)]
            if not any(trimmed):
                continue
            fields = dict(zip(header, trimmed, strict=False))
            row_key = trimmed[key_pos]
            text = " | ".join(f"{label}: {value}" for label, value in fields.items() if value)
            blocks.append(
                ParsedBlock(
                    kind="row",
                    text=text,
                    section_path=f"{template.name} row {row_key}",
                    fields=fields,
                    row_number=row_idx,
                )
            )

        if not blocks:
            raise ParseError(f"xlsx {path.name} matched template {template.name} but has no rows")

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
        attributes["template"] = template.name
        return ParsedDocument(
            meta=enriched, blocks=tuple(blocks), parser=self.name, attributes=attributes
        )

    def _fingerprint(
        self, grid: list[tuple[str, ...]], filename: str
    ) -> tuple[MatrixTemplate, int]:
        for row_idx, values in enumerate(grid[:_MAX_HEADER_SCAN_ROWS], start=1):
            for template in TEMPLATES:
                if values[: len(template.header)] == template.header:
                    return template, row_idx
        raise ParseError(
            f"xlsx {filename} matches no known matrix template within the first "
            f"{_MAX_HEADER_SCAN_ROWS} rows"
        )

    def _preamble_attributes(self, preamble: list[tuple[str, ...]]) -> dict[str, str]:
        return preamble_attributes(preamble)


def preamble_attributes(preamble: list[tuple[str, ...]]) -> dict[str, str]:
    """Title band and revision line above a header row, as document attributes."""
    attributes: dict[str, str] = {}
    for values in preamble:
        for value in values:
            if not value:
                continue
            match = _REVISION_LINE_RE.search(value)
            if match:
                attributes["revision"] = match.group("rev")
                attributes["effective_date"] = match.group("date")
                attributes["approved_by"] = match.group("approver").strip()
            elif "—" in value and "title" not in attributes:
                attributes["title"] = value.split("—", 1)[1].strip()
    return attributes
