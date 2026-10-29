"""Hard gate on controlled-document identity metadata.

A controlled document (SOP, work instruction, quality manual, design/risk/
clinical plan or report) is only trustworthy audit evidence if the assistant can
state which revision was in effect on which date. Ingesting one whose revision
or effective date is missing, empty, or malformed — or whose internal document
number disagrees with its filename identity — would let the assistant cite a
revision it cannot pin to a date, or serve a misfiled document under the wrong
key. Such a document is failed, never indexed.

Record forms (CAPA, complaint, NCR, DHR) are unrevised by design and are not
gated here, and the product requirements spec (design_input) is published
without a document-info control block, so it too is excluded — the gate covers
exactly the doc types whose renderer carries that block.
"""

import re

from gg_ingestion.metrics import IngestGateError
from gg_ingestion.models import DocMeta
from gg_ingestion.registry import parse_effective_date

# Exactly the doc types whose controlled-document renderer emits a Document
# Number / Revision / Effective Date control block. design_input (PRS) is a
# controlled input but is published without that block, so it is excluded to
# avoid failing a document that legitimately carries no revision.
METADATA_GATED_TYPES = frozenset(
    {
        "sop",
        "wi",
        "quality_manual",
        "design_plan",
        "risk_plan",
        "risk_analysis",
        "risk_report",
        "clinical_plan",
        "clinical_report",
    }
)

_GATE = "controlled_metadata"
# Corpus revisions are short uppercase letters (A, B, C). Anything else — a
# stray "Rev A", a draft marker, an empty label — is a malformed revision.
_REVISION_RE = re.compile(r"^[A-Z]{1,3}$")


def enforce_controlled_metadata(meta: DocMeta, attributes: dict[str, str]) -> None:
    """Raise IngestGateError if a controlled document lacks a well-formed identity.

    No-op for uncontrolled and non-gated types."""
    if meta.doc_type not in METADATA_GATED_TYPES:
        return

    revision = (meta.revision or "").strip()
    if not revision:
        raise IngestGateError(
            _GATE,
            f"controlled {meta.doc_type} {meta.doc_key} has no revision; the revision "
            "in effect cannot be established, so it must not be indexed",
        )
    if not _REVISION_RE.match(revision):
        raise IngestGateError(
            _GATE,
            f"controlled {meta.doc_type} {meta.doc_key} revision {revision!r} is not a "
            "recognized revision label (expected letters such as 'A' or 'B')",
        )

    raw_date = attributes.get("effective_date", "").strip()
    if not raw_date:
        raise IngestGateError(
            _GATE,
            f"controlled {meta.doc_type} {meta.doc_key} has no effective date; a revision "
            "cannot be pinned to a date, so it must not be indexed",
        )
    if parse_effective_date(raw_date) is None:
        raise IngestGateError(
            _GATE,
            f"controlled {meta.doc_type} {meta.doc_key} effective date {raw_date!r} is "
            "malformed (expected DD-Mon-YYYY)",
        )

    document_number = attributes.get("document_number", "").strip()
    if not document_number:
        raise IngestGateError(
            _GATE,
            f"controlled {meta.doc_type} {meta.doc_key} carries no document number; its "
            "identity cannot be confirmed against its filename",
        )
    if document_number != meta.doc_key:
        raise IngestGateError(
            _GATE,
            f"controlled document filed as {meta.doc_key} carries internal document number "
            f"{document_number!r}; identity conflict, refusing to index a misfiled document",
        )
