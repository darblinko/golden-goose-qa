"""XML form parser: structured label-value extraction from record exports.

Each direct child of the root element becomes one table block whose fields
map humanized leaf tags to their text ("mdr-record" -> "MDR Record"). The
parser is generic over any flat sectioned XML export; it never guesses at
deeply nested schemas — a leaf inside a nested element gets a path label so
nothing is silently dropped or collapsed.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument
from gg_ingestion.parsers.base import DocumentParser, ParseError

_ACRONYMS = {"mdr", "fda", "udi", "di", "id"}


def _humanize(tag: str) -> str:
    words = tag.replace("-", " ").replace("_", " ").split()
    return " ".join(w.upper() if w in _ACRONYMS else w.capitalize() for w in words)


def _leaf_fields(element: ET.Element, prefix: str = "") -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for child in element:
        label = f"{prefix}{_humanize(child.tag)}"
        if len(child):
            fields.extend(_leaf_fields(child, prefix=f"{label} / "))
        else:
            fields.append((label, (child.text or "").strip()))
    return fields


def _fields_dict(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """Fold ordered (label, value) pairs into a dict without collapsing repeats.
    Repeated sibling paths (e.g. two <device-problem-code> leaves) would
    overwrite under a plain dict; the first keeps the bare label and each later
    occurrence gets a positional suffix ("Device Problem Code 2"), so no value
    is silently dropped and single-value lookups still hit the first."""
    counts: dict[str, int] = {}
    result: dict[str, str] = {}
    for label, value in pairs:
        counts[label] = counts.get(label, 0) + 1
        key = label if counts[label] == 1 else f"{label} {counts[label]}"
        result[key] = value
    return result


class XmlFormParser(DocumentParser):
    name = "xml_form"

    def parse(self, path: Path, meta: DocMeta) -> ParsedDocument:
        try:
            root = ET.parse(str(path)).getroot()
        except ET.ParseError as exc:
            raise ParseError(f"xml {path.name} is not well-formed: {exc}") from exc

        blocks: list[ParsedBlock] = []
        for section in root:
            fields = _fields_dict(_leaf_fields(section))
            if not fields:
                continue
            text = "\n".join(f"{label}: {value}" for label, value in fields.items() if value)
            blocks.append(
                ParsedBlock(
                    kind="table",
                    text=text,
                    section_path=_humanize(section.tag),
                    fields=fields,
                )
            )
        if not blocks:
            raise ParseError(f"xml {path.name} has no leaf elements under root <{root.tag}>")

        return ParsedDocument(
            meta=meta,
            blocks=tuple(blocks),
            parser=self.name,
            attributes={"template": root.tag},
        )
