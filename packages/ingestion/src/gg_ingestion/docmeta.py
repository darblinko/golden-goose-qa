"""Document identity extraction from file paths.

The corpus follows the synthetic corpus numbering conventions (SOP-004, CAPA-2025-007,
C-2025-0142, DHR_L24-1002). Identity comes from the filename; parsers enrich
it with revision and title from content where available. Unrecognized files
are an explicit error at the router, never a guess.
"""

import re
from pathlib import Path

from gg_ingestion.models import DocMeta

_DOC_TYPE_BY_PREFIX = {
    "EMDR": "emdr",
    "QM": "quality_manual",
    "SOP": "sop",
    "WI": "wi",
    "PRS": "design_input",
    "DP": "design_plan",
    "RMP": "risk_plan",
    "RA": "risk_analysis",
    "RMR": "risk_report",
    "TM": "trace_matrix",
    "DFMEA": "dfmea",
    "PFMEA": "pfmea",
    "TRN": "training_matrix",
    "ASL": "supplier_list",
    "ASR": "supplier_audit",
    "AUD": "internal_audit",
    "MRM": "management_review",
    "CIP": "clinical_plan",
    "CER": "clinical_report",
    "CTL": "control_plan",
    "CAPA": "capa",
    "NCR": "ncr",
    "C": "complaint",
    "MDR": "mdr",
    "VTR": "verification_report",
    "DHR": "dhr",
}

# Longest-prefix patterns first so DFMEA does not match as a bare prefix of C.
_KEY_RE = re.compile(
    r"^(?P<key>(?:DFMEA|PFMEA|EMDR|CAPA|AUD|MRM|CIP|CER|CTL|NCR|MDR|VTR|SOP|PRS|RMP|RMR|TRN|ASL|ASR|QM|WI|DP|RA|TM|C)"
    r"-[0-9]{2,4}(?:-[0-9]{2,4})?)"
)
_DHR_RE = re.compile(r"^DHR_(?P<lot>[A-Z0-9-]+?)(?P<scanned>_scanned)?$")


class UnrecognizedDocumentError(ValueError):
    pass


def doc_meta_from_path(path: Path) -> DocMeta:
    stem = path.stem
    file_format = path.suffix.lstrip(".").lower()

    dhr = _DHR_RE.match(stem)
    if dhr:
        lot = dhr.group("lot")
        return DocMeta(
            doc_key=f"DHR-{lot}",
            doc_type="dhr_scanned" if dhr.group("scanned") else "dhr",
            title=f"Device History Record — Lot {lot}",
            file_format=file_format,
        )

    match = _KEY_RE.match(stem)
    if not match:
        raise UnrecognizedDocumentError(f"no document key recognized in filename: {path.name}")
    doc_key = match.group("key")
    prefix = doc_key.split("-", 1)[0]
    doc_type = _DOC_TYPE_BY_PREFIX[prefix]

    remainder = stem[len(doc_key) :].strip("_")
    # Archived copies carry a _Rev_X filename suffix; identity and title stay
    # canonical — the revision itself comes from the document content.
    remainder = re.sub(r"_Rev_[A-Z]$", "", remainder)
    title = remainder.replace("_", " ").strip() or doc_key
    return DocMeta(doc_key=doc_key, doc_type=doc_type, title=title, file_format=file_format)
