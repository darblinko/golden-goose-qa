"""A record's own event date becomes its effective_from, so an as-of filter
excludes a complaint, NCR, CAPA or audit dated after the requested moment.
Before this, record forms reached the index with effective_from=None and
passed every as-of filter as undated."""

from datetime import date

from gg_ingestion.extract.records import record_event_date
from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument
from gg_ingestion.pipeline import version_effective_from


def _pdf(doc_type: str, page_text: str) -> ParsedDocument:
    return ParsedDocument(
        meta=DocMeta(doc_key="X-1", doc_type=doc_type, title="t", file_format="pdf"),
        blocks=(ParsedBlock(kind="page", text=page_text, page=1),),
        parser="pdf_form",
    )


def _table(doc_type: str, fields: dict[str, str], file_format: str = "docx") -> ParsedDocument:
    return ParsedDocument(
        meta=DocMeta(doc_key="X-1", doc_type=doc_type, title="t", file_format=file_format),
        blocks=(ParsedBlock(kind="table", text="", fields=fields),),
        parser="docx_narrative",
    )


_COMPLAINT_TEXT = (
    "Complaint Number\nC-2025-0101\nDate Received\n14-Mar-2025\nDevice Model\nMP-100\n"
    "Lot Number\nL1\nFailure Category\nocclusion\nDescription\nd\n"
    "Investigation Summary\ns\nRisk File Evaluation\nr\nMDR Filed\nNo\nStatus\nOpen\n"
    "Date Closed\nOpen\n"
)


def test_complaint_takes_its_received_date():
    assert record_event_date(_pdf("complaint", _COMPLAINT_TEXT)) == date(2025, 3, 14)


def test_docx_records_take_their_labelled_date():
    capa = _table("capa", {"CAPA Number": "CAPA-2025-014", "Date Opened": "02-Feb-2025"})
    audit = _table("internal_audit", {"Audit Date": "10-Jun-2024"})
    review = _table("management_review", {"Meeting Date": "05-Dec-2025"})
    assert record_event_date(capa) == date(2025, 2, 2)
    assert record_event_date(audit) == date(2024, 6, 10)
    assert record_event_date(review) == date(2025, 12, 5)


def test_emdr_takes_its_iso_submission_date():
    emdr = _table("emdr", {"Report Number": "EMDR-0001", "Date Submitted": "2024-02-25"}, "xml")
    assert record_event_date(emdr) == date(2024, 2, 25)


def test_in_progress_verification_is_undated():
    report = _pdf(
        "verification_report",
        "Report Number\nVTR-1\nProtocol\nVTP-001\nTitle\nt\nRequirements Verified\nREQ-1\n"
        "Result\nPending\nDate Completed\nIn progress\n",
    )
    assert record_event_date(report) is None


def test_controlled_documents_have_no_event_date():
    assert record_event_date(_table("sop", {"Effective Date": "01-Jan-2024"})) is None


def test_pipeline_uses_the_event_date_for_records_only():
    assert version_effective_from(_pdf("complaint", _COMPLAINT_TEXT)) == date(2025, 3, 14)
    sop = ParsedDocument(
        meta=DocMeta(doc_key="SOP-004", doc_type="sop", title="t", file_format="docx"),
        blocks=(),
        parser="docx_narrative",
        attributes={"effective_date": "15-Jan-2024"},
    )
    assert version_effective_from(sop) == date(2024, 1, 15)
