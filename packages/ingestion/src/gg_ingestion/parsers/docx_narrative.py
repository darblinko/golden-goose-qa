"""Native structural parser for born-digital Word documents.

Walks body content in document order (python-docx iter_inner_content), builds a
section path from heading styles, and recognizes the two controlled-document
table shapes: header-row tables (document info, revision history) and two-column
label/value forms (CAPA records). Document attributes (revision, effective
date, approver) are extracted from those tables when present.
"""

from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument
from gg_ingestion.parsers.base import DocumentParser, ParseError

_DOC_INFO_HEADER = ("Document Number", "Revision", "Effective Date", "Department")
_REV_HISTORY_HEADER = ("Rev", "Date", "Description", "Author", "Approved By")
_CONTROLLED_TYPES = frozenset(
    {
        "sop",
        "wi",
        "quality_manual",
        "design_plan",
        "design_input",
        "risk_plan",
        "risk_analysis",
        "risk_report",
        "clinical_plan",
        "clinical_report",
    }
)


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style.name if paragraph.style is not None else ""
    if style == "Title":
        return 0
    if style.startswith("Heading "):
        try:
            return int(style.removeprefix("Heading "))
        except ValueError:
            return None
    return None


def _table_rows(table: Table) -> list[tuple[str, ...]]:
    return [tuple(cell.text.strip() for cell in row.cells) for row in table.rows]


def _rows_as_text(rows: list[tuple[str, ...]]) -> str:
    return "\n".join(" | ".join(row) for row in rows)


def _remember(attributes: dict[str, str], key: str, value: str) -> None:
    """Record the first non-empty value seen for an attribute. A blank cell must
    not claim the slot: the document-info table is read before the revision
    history, and an empty Revision/Effective Date cell there would otherwise
    block the value the history genuinely carries."""
    if value and key not in attributes:
        attributes[key] = value


class DocxNarrativeParser(DocumentParser):
    name = "docx_narrative"

    def parse(self, path: Path, meta: DocMeta) -> ParsedDocument:
        try:
            document = Document(str(path))
        except Exception as exc:
            raise ParseError(f"cannot open docx {path.name}: {exc}") from exc

        blocks: list[ParsedBlock] = []
        warnings: list[str] = []
        attributes: dict[str, str] = {}
        title = meta.title
        sections: dict[int, str] = {}

        def section_path() -> str:
            return " > ".join(sections[level] for level in sorted(sections) if level >= 2)

        for item in document.iter_inner_content():
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if not text:
                    continue
                level = _heading_level(item)
                if level is None:
                    blocks.append(
                        ParsedBlock(kind="paragraph", text=text, section_path=section_path())
                    )
                    continue
                if level == 1 and not attributes.get("title_heading"):
                    attributes["title_heading"] = text
                    title = _title_from_heading(text, meta.doc_key) or title
                if level >= 1:
                    sections[level] = text
                    for deeper in [k for k in sections if k > level]:
                        del sections[deeper]
                blocks.append(
                    ParsedBlock(
                        kind="heading",
                        text=text,
                        heading_level=level,
                        section_path=section_path(),
                    )
                )
            elif isinstance(item, Table):
                rows = _table_rows(item)
                if not rows:
                    continue
                blocks.append(self._table_block(rows, section_path(), attributes))

        if not blocks:
            raise ParseError(f"docx {path.name} produced no content blocks")
        if "revision" not in attributes and meta.doc_type in _CONTROLLED_TYPES:
            warnings.append("no revision attribute extracted")

        enriched = DocMeta(
            doc_key=meta.doc_key,
            doc_type=meta.doc_type,
            title=title,
            revision=attributes.get("revision"),
            file_format=meta.file_format,
        )
        return ParsedDocument(
            meta=enriched,
            blocks=tuple(blocks),
            parser=self.name,
            warnings=tuple(warnings),
            attributes=attributes,
        )

    def _table_block(
        self,
        rows: list[tuple[str, ...]],
        section: str,
        attributes: dict[str, str],
    ) -> ParsedBlock:
        if rows[0] == _DOC_INFO_HEADER and len(rows) >= 2:
            fields = dict(zip(_DOC_INFO_HEADER, rows[1], strict=False))
            _remember(attributes, "document_number", fields.get("Document Number", ""))
            _remember(attributes, "revision", fields.get("Revision", ""))
            _remember(attributes, "effective_date", fields.get("Effective Date", ""))
            _remember(attributes, "department", fields.get("Department", ""))
            return ParsedBlock(
                kind="table", text=_rows_as_text(rows), section_path=section, fields=fields
            )
        if rows[0] == _REV_HISTORY_HEADER and len(rows) >= 2:
            current = dict(zip(_REV_HISTORY_HEADER, rows[-1], strict=False))
            _remember(attributes, "revision", current.get("Rev", ""))
            _remember(attributes, "effective_date", current.get("Date", ""))
            _remember(attributes, "approved_by", current.get("Approved By", ""))
            return ParsedBlock(
                kind="table", text=_rows_as_text(rows), section_path=section, fields={}
            )
        if all(len(row) == 2 for row in rows):
            fields = {label: value for label, value in rows if label}
            text = "\n".join(f"{label}: {value}" for label, value in rows)
            return ParsedBlock(kind="table", text=text, section_path=section, fields=fields)
        return ParsedBlock(kind="table", text=_rows_as_text(rows), section_path=section)


def _title_from_heading(heading: str, doc_key: str) -> str | None:
    parts = [p.strip() for p in heading.split("—")]
    if len(parts) == 2:
        candidates = [p for p in parts if doc_key not in p]
        if candidates:
            return candidates[0]
    return None
