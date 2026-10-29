"""Field extraction from parsed record forms.

docx forms already carry label/value fields from the parser. Born-digital
PDF forms are page text where each label sits on its own line followed by
its (possibly wrapped) value lines — extraction walks the known label set
for the form type, in order, and stops at the form's footer note. Label
sets are per-template, exactly like a real QMS where record forms are
controlled templates.
"""

import re
from datetime import date, datetime

from gg_ingestion.models import ParsedDocument

PDF_FORM_LABELS: dict[str, tuple[str, ...]] = {
    "ncr": (
        "NCR Number",
        "Date Opened",
        "Part Number",
        "Supplier",
        "Description of Nonconformance",
        "Disposition",
        "Linked CAPA",
        "Status",
        "Date Closed",
    ),
    "complaint": (
        "Complaint Number",
        "Date Received",
        "Device Model",
        "Lot Number",
        "Failure Category",
        "Description",
        "Investigation Summary",
        "Risk File Evaluation",
        "MDR Filed",
        "Status",
        "Date Closed",
    ),
    "mdr": (
        "MDR Report Number",
        "Source Complaint",
        "Date Submitted to FDA",
        "Event Type",
        "Device Model",
        "Lot Number",
        "Event Description",
    ),
    "verification_report": (
        "Report Number",
        "Protocol",
        "Title",
        "Requirements Verified",
        "Result",
        "Date Completed",
    ),
}

# Record forms end with a boilerplate note paragraph below the field table.
_FOOTER_NOTE_RE = re.compile(r"^(?:Submitted|Dispositioned|Handled|Executed) per\b")

_PAREN_ID_RE = re.compile(r"\(([A-Z]+-[0-9-]+)\)")


class RecordExtractionError(ValueError):
    pass


def pdf_form_fields(parsed: ParsedDocument) -> dict[str, str]:
    labels = PDF_FORM_LABELS.get(parsed.meta.doc_type)
    if labels is None:
        raise RecordExtractionError(f"no PDF form labels for doc_type {parsed.meta.doc_type}")
    text = "\n".join(b.text for b in parsed.blocks if b.kind == "page")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    label_set = set(labels)
    fields: dict[str, str] = {}
    current: str | None = None
    for line in lines:
        if line in label_set:
            current = line
            fields[current] = ""
            continue
        if current is None:
            continue
        if _FOOTER_NOTE_RE.match(line):
            current = None
            continue
        fields[current] = f"{fields[current]} {line}".strip() if fields[current] else line

    missing = [label for label in labels if label not in fields]
    if missing:
        raise RecordExtractionError(
            f"{parsed.meta.doc_key}: form labels missing from page text: {', '.join(missing)}"
        )
    return fields


def docx_form_fields(parsed: ParsedDocument) -> dict[str, str]:
    """Fields from the first two-column label/value table block."""
    for block in parsed.blocks:
        if block.kind == "table" and block.fields:
            return dict(block.fields)
    raise RecordExtractionError(f"{parsed.meta.doc_key}: no label/value form table found")


# The "no date yet" sentinels a controlled form prints when a milestone has not
# happened: an open record has no closed date, an unstarted check no completion
# date. These map to None (genuinely absent). Anything else that is non-empty
# but not a parseable date is a malformed field — a real extraction fault that
# must surface, never be quietly read as an absent date (which the registers
# derive is_open from, turning a closed record into a phantom open one).
_DATE_SENTINELS = frozenset(
    {"", "—", "-", "open", "not completed", "not started", "not applicable", "n/a", "none"}
)


def parse_form_date(value: str) -> date | None:
    """Dates like 23-Aug-2024. Recognized sentinels (Open, Not completed, —)
    are a genuinely absent date and become None. A non-empty value that is
    neither a sentinel nor a parseable date is a malformed field and raises
    RecordExtractionError, so a corrupt close date can never be silently
    classified as an open record."""
    stripped = value.strip()
    if stripped.lower() in _DATE_SENTINELS:
        return None
    try:
        return datetime.strptime(stripped, "%d-%b-%Y").date()
    except ValueError:
        raise RecordExtractionError(f"unparseable date field: {value!r}") from None


def id_in_parens(value: str) -> str | None:
    """The id in "Apex Feedthrough Technologies (SUP-004)" style values."""
    match = _PAREN_ID_RE.search(value)
    return match.group(1) if match else None


def value_or_none(value: str, *sentinels: str) -> str | None:
    stripped = value.strip()
    if not stripped or stripped in sentinels:
        return None
    return stripped
