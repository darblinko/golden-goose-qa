from datetime import date

import pytest
from gg_ingestion.extract.records import (
    RecordExtractionError,
    id_in_parens,
    parse_form_date,
    pdf_form_fields,
    value_or_none,
)
from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument


def _mdr_document(page_text: str) -> ParsedDocument:
    return ParsedDocument(
        meta=DocMeta(
            doc_key="MDR-2025-0004",
            doc_type="mdr",
            title="MedWatch 3500A Summary",
            file_format="pdf",
        ),
        blocks=(ParsedBlock(kind="page", text=page_text, page=1),),
        parser="pdf_form",
    )


class TestPdfFormFields:
    def test_wrapped_values_join_and_footer_stops(self):
        parsed = _mdr_document(
            "Halvern Medical\n"
            "MedWatch 3500A Summary\n"
            "MDR Report Number\nMDR-2025-0004\n"
            "Source Complaint\nC-2025-0104\n"
            "Date Submitted to FDA\n11-Apr-2025\n"
            "Event Type\nMalfunction\n"
            "Device Model\nCG-3000\n"
            "Lot Number\nL24-0031\n"
            "Event Description\nDevice failed during checkout.\n"
            "Second line of the same description.\n"
            "Submitted per SOP-014 Medical Device Reporting.\n"
        )
        fields = pdf_form_fields(parsed)
        assert fields["MDR Report Number"] == "MDR-2025-0004"
        assert fields["Event Description"] == (
            "Device failed during checkout. Second line of the same description."
        )
        assert "SOP-014" not in fields["Event Description"]

    def test_missing_label_raises(self):
        parsed = _mdr_document("MDR Report Number\nMDR-2025-0004\n")
        with pytest.raises(RecordExtractionError, match="labels missing"):
            pdf_form_fields(parsed)

    def test_unknown_doc_type_raises(self):
        parsed = ParsedDocument(
            meta=DocMeta(doc_key="SOP-001", doc_type="sop", title="t", file_format="pdf"),
            blocks=(),
            parser="pdf_form",
        )
        with pytest.raises(RecordExtractionError, match="no PDF form labels"):
            pdf_form_fields(parsed)


def test_parse_form_date_and_sentinels():
    assert parse_form_date("23-Aug-2024") == date(2024, 8, 23)
    assert parse_form_date("Open") is None
    assert parse_form_date("Not completed") is None
    assert parse_form_date("—") is None
    assert parse_form_date("") is None
    assert parse_form_date("  n/a ") is None


def test_parse_form_date_rejects_malformed_dates():
    # A non-empty, non-sentinel value that will not parse is an extraction
    # fault: it must raise, never quietly return None (which the registers read
    # as "no close date" and would classify a closed record as still open).
    with pytest.raises(RecordExtractionError, match="unparseable date"):
        parse_form_date("2024-08-23")  # ISO order the form template never prints
    with pytest.raises(RecordExtractionError, match="unparseable date"):
        parse_form_date("32-Aug-2024")  # impossible day
    with pytest.raises(RecordExtractionError, match="unparseable date"):
        parse_form_date("closed last spring")


def test_id_in_parens():
    assert id_in_parens("Apex Feedthrough Technologies (SUP-004)") == "SUP-004"
    assert id_in_parens("Internal") is None


def test_value_or_none():
    assert value_or_none("  NCR-2024-001 ") == "NCR-2024-001"
    assert value_or_none("None", "None") is None
    assert value_or_none("", "None") is None
