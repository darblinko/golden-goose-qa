"""Parser tests against a freshly generated synthetic corpus (seed 42)."""

from typing import Any, cast

import pytest
from gg_common.providers.fakes import FakeOCRProvider
from gg_common.settings import RetrievalSettings
from gg_ingestion.chunking import chunk_document
from gg_ingestion.docmeta import doc_meta_from_path
from gg_ingestion.metrics import IngestGateError, compute_metrics, enforce_gates
from gg_ingestion.models import DocMeta
from gg_ingestion.parsers.base import NoTextLayerError, ParseError
from gg_ingestion.parsers.pdf_form import PdfFormParser
from gg_ingestion.parsers.pdf_scanned import ScannedPdfParser
from gg_ingestion.parsers.router import ParserRouter
from gg_ingestion.parsers.xlsx_grid import XlsxGridParser
from gg_ingestion.parsers.xlsx_matrix import XlsxMatrixParser
from gg_ingestion.parsers.xml_form import XmlFormParser
from gg_ingestion.pipeline import IngestionPipeline


@pytest.fixture(scope="session")
def router():
    return ParserRouter(ocr=FakeOCRProvider())


def _parse(router, corpus_dir, rel):
    path = corpus_dir / rel
    route = router.route(path)
    assert route.parser is not None, route.skip_reason
    return route.parser.parse(path, route.meta)


class TestDocxNarrative:
    def test_sop_sections_and_attributes(self, router, corpus_dir):
        parsed = _parse(
            router, corpus_dir, "01_quality_system/SOP-004_Corrective_and_Preventive_Action.docx"
        )
        assert parsed.meta.revision == "B"
        assert parsed.attributes["effective_date"] == "30-Apr-2026"
        assert parsed.attributes["department"] == "Quality Assurance"
        assert parsed.attributes["approved_by"]
        assert parsed.warnings == ()
        sections = {b.section_path for b in parsed.blocks if b.section_path}
        assert {"1. Purpose", "2. Scope", "3. Procedure", "4. Records"} <= sections
        kinds = {b.kind for b in parsed.blocks}
        assert kinds == {"heading", "paragraph", "table"}

    def test_capa_label_value_table(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "04_capa/CAPA-2025-007.docx")
        assert parsed.meta.title == "Corrective and Preventive Action Record"
        table = next(b for b in parsed.blocks if b.kind == "table")
        assert table.fields["CAPA Number"] == "CAPA-2025-007"
        assert "Source" in table.fields
        assert "CAPA Number: CAPA-2025-007" in table.text
        # CAPA records are uncontrolled: no revision, and no warning about it
        assert parsed.meta.revision is None
        assert parsed.warnings == ()

    def test_archived_revision_parses_with_prior_identity(self, router, corpus_dir):
        """The archived copy shares SOP-004's doc_key but carries the prior
        revision letter, an earlier effective date, and a shorter procedure —
        the substance the as-of retrieval path exists to reach."""
        current = _parse(
            router, corpus_dir, "01_quality_system/SOP-004_Corrective_and_Preventive_Action.docx"
        )
        archived = _parse(
            router,
            corpus_dir,
            "01_quality_system/archive/SOP-004_Corrective_and_Preventive_Action_Rev_A.docx",
        )
        assert archived.meta.doc_key == "SOP-004"
        assert archived.meta.revision == "A"
        assert current.meta.revision == "B"
        assert archived.attributes["effective_date"] != current.attributes["effective_date"]
        current_steps = [b for b in current.blocks if b.section_path == "3. Procedure"]
        archived_steps = [b for b in archived.blocks if b.section_path == "3. Procedure"]
        assert len(archived_steps) < len(current_steps)

    def test_sop_016_stale_reference_survives_parsing(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "01_quality_system/SOP-016_Labeling_Control.docx")
        body = "\n".join(b.text for b in parsed.blocks)
        assert "SOP-016" in parsed.meta.doc_key
        assert body  # seeded-defect doc parses like any other

    def test_clinical_report_is_controlled_narrative(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "13_clinical/CER-100_Clinical_Evaluation_Report.docx")
        assert parsed.meta.title == "Clinical Evaluation Report"
        assert parsed.meta.revision is not None
        assert parsed.attributes["department"] == "Regulatory Affairs"
        assert parsed.warnings == ()
        sections = {b.section_path for b in parsed.blocks if b.section_path}
        assert {"3. Clinical Data Sources", "5. Benefit-Risk Conclusion", "References"} <= sections

    def test_document_number_captured_from_doc_info(self, router, corpus_dir):
        # The internal Document Number feeds the controlled-metadata identity gate,
        # so it must be captured and, for a well-formed corpus doc, equal the doc_key.
        parsed = _parse(
            router, corpus_dir, "01_quality_system/SOP-004_Corrective_and_Preventive_Action.docx"
        )
        assert parsed.attributes["document_number"] == "SOP-004"


class TestDocInfoRevisionFallback:
    def _build(self, path, doc_info_revision):
        from docx import Document

        document = Document()
        document.add_heading("Halvern Medical", level=0)
        document.add_heading("SOP-999 — Blank Revision Cell", level=1)
        info = document.add_table(rows=2, cols=4)
        for i, label in enumerate(("Document Number", "Revision", "Effective Date", "Department")):
            info.rows[0].cells[i].text = label
        for i, value in enumerate(("SOP-999", doc_info_revision, "30-Apr-2026", "Quality")):
            info.rows[1].cells[i].text = value
        history = document.add_table(rows=2, cols=5)
        for i, label in enumerate(("Rev", "Date", "Description", "Author", "Approved By")):
            history.rows[0].cells[i].text = label
        for i, value in enumerate(("B", "30-Apr-2026", "Update", "A. Author", "Q. Approver")):
            history.rows[1].cells[i].text = value
        document.add_paragraph("Body text so the document has a content block.")
        document.save(str(path))

    def test_blank_doc_info_revision_falls_back_to_history(self, tmp_path):
        # A blank Revision cell in the document-info table must not claim the slot
        # and block the revision-history fallback, or a controlled document would
        # be indexed with an empty revision it actually carries in its history.
        from gg_ingestion.parsers.docx_narrative import DocxNarrativeParser

        path = tmp_path / "SOP-999_blank_rev.docx"
        self._build(path, doc_info_revision="")
        meta = DocMeta(doc_key="SOP-999", doc_type="sop", title="SOP", file_format="docx")

        parsed = DocxNarrativeParser().parse(path, meta)
        assert parsed.meta.revision == "B"
        assert parsed.attributes["document_number"] == "SOP-999"
        assert parsed.attributes["effective_date"] == "30-Apr-2026"

    def test_present_doc_info_revision_wins(self, tmp_path):
        from gg_ingestion.parsers.docx_narrative import DocxNarrativeParser

        path = tmp_path / "SOP-999_rev_c.docx"
        self._build(path, doc_info_revision="C")
        meta = DocMeta(doc_key="SOP-999", doc_type="sop", title="SOP", file_format="docx")

        parsed = DocxNarrativeParser().parse(path, meta)
        assert parsed.meta.revision == "C"


class TestGovernanceForms:
    def test_internal_audit_form(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "11_internal_audit/AUD-2025-01.docx")
        assert parsed.meta.title == "Internal Audit Report"
        assert parsed.meta.revision is None
        assert parsed.warnings == ()
        table = next(b for b in parsed.blocks if b.kind == "table")
        assert table.fields["Report Number"] == "AUD-2025-01"
        assert table.fields["Lead Auditor"]
        assert table.fields["Documents in Scope"]
        findings = [b for b in parsed.blocks if b.section_path == "Findings"]
        assert findings

    def test_management_review_form(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "12_management_review/MRM-2025-02.docx")
        assert parsed.meta.title == "Management Review Minutes"
        assert parsed.meta.revision is None
        assert parsed.warnings == ()
        table = next(b for b in parsed.blocks if b.kind == "table")
        assert table.fields["Review Number"] == "MRM-2025-02"
        assert table.fields["Internal Audits Conducted"].startswith("AUD-")
        assert table.fields["CAPAs Opened"].isdigit()
        decisions = [b for b in parsed.blocks if b.section_path == "Decisions and Actions"]
        assert decisions


class TestXlsxMatrix:
    def test_trace_matrix_rows(self, router, corpus_dir):
        parsed = _parse(
            router, corpus_dir, "02_design_history_file/TM-100_Design_Traceability_Matrix.xlsx"
        )
        assert parsed.attributes["template"] == "trace_matrix"
        assert parsed.meta.revision == "A"
        assert all(b.kind == "row" for b in parsed.blocks)
        assert len(parsed.blocks) == 40
        first = parsed.blocks[0]
        assert first.section_path == "trace_matrix row REQ-001"
        assert first.fields["Requirement ID"] == "REQ-001"
        # Data starts at row 5: rows 1-2 title band, row 3 grouped header band,
        # row 4 flat field headers.
        assert first.row_number == 5

    def test_trace_matrix_category_merges_forward_fill(self, router, corpus_dir):
        # The Category column is a vertical merge down each subsystem run; every
        # continuation row must normalize back to its category via the parser's
        # merge forward-fill, not come back blank.
        parsed = _parse(
            router, corpus_dir, "02_design_history_file/TM-100_Design_Traceability_Matrix.xlsx"
        )
        by_req = {b.fields["Requirement ID"]: b for b in parsed.blocks}
        for req_id in ("REQ-001", "REQ-002", "REQ-005"):
            assert by_req[req_id].fields["Category"] == "electrical"

    def test_trace_matrix_gap_row_keeps_empty_cells(self, router, corpus_dir):
        parsed = _parse(
            router, corpus_dir, "02_design_history_file/TM-100_Design_Traceability_Matrix.xlsx"
        )
        req17 = next(b for b in parsed.blocks if b.fields.get("Requirement ID") == "REQ-017")
        assert req17.fields["Verification Report"] == ""
        assert req17.fields["Result"] == ""
        # empty cells are omitted from text, never padded with fake values
        assert "Verification Report" not in req17.text

    def test_fmea_rows_and_banner_attribute(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "03_risk_management/DFMEA-100_Design_FMEA.xlsx")
        assert parsed.attributes["template"] == "fmea"
        assert parsed.meta.revision == "A"
        first = parsed.blocks[0]
        assert first.fields["#"] == "1"
        assert {"Failure Mode", "S", "O", "D", "AP"} <= set(first.fields)
        ft210 = [b for b in parsed.blocks if "FT-210" in b.text]
        assert ft210, "seeded FT-210 fault-tree reference must appear in FMEA rows"

    def test_control_plan_rows(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "03_risk_management/CTL-100_Process_Control_Plan.xlsx")
        assert parsed.attributes["template"] == "control_plan"
        assert parsed.meta.revision is not None
        assert len(parsed.blocks) == 11
        first = parsed.blocks[0]
        assert first.fields["#"] == "1"
        assert first.fields["PFMEA Ref"] == "PFMEA-100 row 1"
        assert {"Characteristic", "Specification", "Reference", "Reaction Plan"} <= set(
            first.fields
        )

    def test_multi_sheet_workbook_rejected(self, tmp_path):
        # Both spreadsheet parsers read only the active sheet; a second sheet
        # could hide an entire record set, so an unexpected multi-sheet workbook
        # must fail rather than be parsed partially.
        from openpyxl import Workbook

        wb = Workbook()
        wb.active.title = "Trace Matrix"
        wb.create_sheet("Hidden Records")
        path = tmp_path / "TM-999_two_sheets.xlsx"
        wb.save(str(path))
        meta = DocMeta(doc_key="TM-999", doc_type="trace_matrix", title="TM", file_format="xlsx")
        with pytest.raises(ParseError, match="worksheets"):
            XlsxMatrixParser().parse(path, meta)


class TestPdfForm:
    def test_complaint_page_extraction(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "06_complaints/C-2025-0142.pdf")
        assert [b.kind for b in parsed.blocks] == ["page"]
        assert parsed.blocks[0].page == 1
        assert "C-2025-0142" in parsed.blocks[0].text

    def test_born_digital_dhr_parses(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "08_production_records/DHR_L250028.pdf")
        assert parsed.meta.doc_type == "dhr"
        assert parsed.blocks

    def test_scanned_pdf_raises_no_text_layer(self, corpus_dir):
        path = corpus_dir / "08_production_records/DHR_L250007_scanned.pdf"
        meta = doc_meta_from_path(path)
        with pytest.raises(NoTextLayerError, match="OCR path"):
            PdfFormParser().parse(path, meta)


class TestScannedPdf:
    async def test_scanned_dhr_parses_via_ocr(self, router, corpus_dir):
        path = corpus_dir / "08_production_records/DHR_L250007_scanned.pdf"
        route = router.route(path)
        assert route.parser is router.scanned
        parsed = await route.parser.parse(path, route.meta)
        assert parsed.parser == "pdf_scanned"
        assert parsed.meta.doc_type == "dhr_scanned"
        assert [b.kind for b in parsed.blocks] == ["page"]
        assert parsed.blocks[0].page == 1
        assert parsed.blocks[0].text.startswith("FAKE_OCR_PAGE:")
        assert parsed.attributes["ocr_pages"] == "1"
        assert parsed.attributes["ocr_min_confidence"] == "0.9500"

    async def test_degraded_scan_blocked_by_confidence_gate(self, corpus_dir):
        path = corpus_dir / "08_production_records/DHR_L250007_scanned.pdf"
        meta = doc_meta_from_path(path)
        parser = ScannedPdfParser(FakeOCRProvider(confidence=0.4))
        parsed = await parser.parse(path, meta)
        chunks = chunk_document(parsed, content_hash="degraded", settings=RetrievalSettings())
        metrics = compute_metrics(parsed, chunks, sanitize_hits=0, seconds=0.0)
        assert metrics.ocr_min_confidence == 0.4
        with pytest.raises(IngestGateError, match="ocr_confidence"):
            enforce_gates(metrics)

    async def test_born_digital_pdf_has_nothing_to_ocr(self, corpus_dir):
        path = corpus_dir / "08_production_records/DHR_L250028.pdf"
        meta = doc_meta_from_path(path)
        with pytest.raises(ParseError, match="no embedded page images"):
            await ScannedPdfParser(FakeOCRProvider()).parse(path, meta)

    async def test_pipeline_reroutes_textless_pdf_to_ocr(self, corpus_dir):
        """A scan that reaches the born-digital parser (e.g. misnamed file)
        still ends up on the OCR path, with the detour recorded."""
        pipeline = IngestionPipeline(
            settings=cast(Any, None),
            session_factory=cast(Any, None),
            qdrant=cast(Any, None),
            object_store=cast(Any, None),
            embeddings=cast(Any, None),
            ocr=FakeOCRProvider(),
        )
        path = corpus_dir / "08_production_records/DHR_L250007_scanned.pdf"
        meta = doc_meta_from_path(path)
        parsed = await pipeline._parse(PdfFormParser(), path, meta)
        assert parsed.parser == "pdf_scanned"
        assert parsed.warnings[0].startswith("no text layer")


class TestHybridPdf:
    """A hybrid PDF pairs born-digital text pages with inserted scans that have
    no text layer. The born-digital parse succeeds on the text pages, so it
    never raises NoTextLayerError; without a per-page fallback the scanned pages
    are dropped with only a warning and their evidence never reaches retrieval."""

    @staticmethod
    def _hybrid_pdf(corpus_dir, tmp_path):
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.append(str(corpus_dir / "06_complaints/C-2025-0142.pdf"))  # born-digital text
        writer.append(str(corpus_dir / "08_production_records/DHR_L250007_scanned.pdf"))  # image
        out = tmp_path / "HYB-1_born_and_scanned.pdf"
        with out.open("wb") as handle:
            writer.write(handle)
        return out

    @staticmethod
    def _pipeline(ocr):
        return IngestionPipeline(
            settings=cast(Any, None),
            session_factory=cast(Any, None),
            qdrant=cast(Any, None),
            object_store=cast(Any, None),
            embeddings=cast(Any, None),
            ocr=ocr,
        )

    async def test_scanned_page_recovered_via_per_page_ocr(self, corpus_dir, tmp_path):
        path = self._hybrid_pdf(corpus_dir, tmp_path)
        meta = DocMeta(doc_key="HYB-1", doc_type="complaint", title="Hybrid", file_format="pdf")
        parsed = await self._pipeline(FakeOCRProvider())._parse(PdfFormParser(), path, meta)

        by_page = {b.page: b for b in parsed.blocks}
        assert set(by_page) == {1, 2}
        # Page 1 kept its born-digital text; page 2 (image-only) was OCR'd.
        assert "C-2025-0142" in by_page[1].text
        assert by_page[2].text.startswith("FAKE_OCR_PAGE:")
        assert parsed.attributes["ocr_min_confidence"] == "0.9500"
        assert any("per-page OCR fallback" in w for w in parsed.warnings)

    async def test_recovered_ocr_page_still_gated_by_confidence(self, corpus_dir, tmp_path):
        path = self._hybrid_pdf(corpus_dir, tmp_path)
        meta = DocMeta(doc_key="HYB-1", doc_type="complaint", title="Hybrid", file_format="pdf")
        pipeline = self._pipeline(FakeOCRProvider(confidence=0.4))
        parsed = await pipeline._parse(PdfFormParser(), path, meta)

        chunks = chunk_document(parsed, content_hash="hybrid", settings=RetrievalSettings())
        metrics = compute_metrics(parsed, chunks, sanitize_hits=0, seconds=0.0)
        assert metrics.ocr_min_confidence == 0.4
        with pytest.raises(IngestGateError, match="ocr_confidence"):
            enforce_gates(metrics)

    async def test_purely_born_digital_pdf_left_untouched(self, corpus_dir):
        # Nothing to recover: ocr_selected_pages returns None and the document
        # is returned unchanged (no OCR attributes, no fallback warning).
        path = corpus_dir / "06_complaints/C-2025-0142.pdf"
        meta = doc_meta_from_path(path)
        parsed = await self._pipeline(FakeOCRProvider())._parse(PdfFormParser(), path, meta)
        assert "ocr_min_confidence" not in parsed.attributes
        assert not any("per-page OCR fallback" in w for w in parsed.warnings)

    async def test_ocr_selected_pages_returns_none_when_all_excluded(self, corpus_dir):
        path = corpus_dir / "08_production_records/DHR_L250007_scanned.pdf"
        meta = doc_meta_from_path(path)
        parser = ScannedPdfParser(FakeOCRProvider())
        assert await parser.ocr_selected_pages(path, meta, exclude_pages={1}) is None
        recovered = await parser.ocr_selected_pages(path, meta, exclude_pages=set())
        assert recovered is not None
        assert [b.page for b in recovered.blocks] == [1]

    async def test_born_digital_page_then_unrecoverable_blank_fails(self, corpus_dir, tmp_path):
        # A born-digital text page followed by a truly blank page (no text layer
        # and no embedded image) cannot be recovered by OCR. Rather than index a
        # document silently missing page 2, coverage enforcement fails the parse.
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.append(str(corpus_dir / "06_complaints/C-2025-0142.pdf"))  # page 1: text
        writer.add_blank_page(width=612, height=792)  # page 2: no text, no image
        path = tmp_path / "GAP-1_text_then_blank.pdf"
        with path.open("wb") as handle:
            writer.write(handle)
        meta = DocMeta(doc_key="GAP-1", doc_type="complaint", title="Gap", file_format="pdf")
        with pytest.raises(ParseError, match=r"page\(s\) \[2\] unrecovered"):
            await self._pipeline(FakeOCRProvider())._parse(PdfFormParser(), path, meta)

    async def test_scanned_page_then_imageless_page_fails(self, corpus_dir, tmp_path):
        # A scanned image page followed by an imageless page: the born-digital
        # parser finds no text and reroutes to OCR, which recovers page 1 but
        # cannot recover the imageless page 2. Coverage enforcement fails.
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.append(str(corpus_dir / "08_production_records/DHR_L250007_scanned.pdf"))  # image
        writer.add_blank_page(width=612, height=792)  # imageless
        path = tmp_path / "GAP-2_scan_then_blank.pdf"
        with path.open("wb") as handle:
            writer.write(handle)
        meta = DocMeta(doc_key="GAP-2", doc_type="dhr", title="Gap", file_format="pdf")
        with pytest.raises(ParseError, match=r"page\(s\) \[2\] unrecovered"):
            await self._pipeline(FakeOCRProvider())._parse(PdfFormParser(), path, meta)


class TestXmlForm:
    def test_emdr_sections_and_fields(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "10_regulatory/EMDR-0001.xml")
        assert parsed.parser == "xml_form"
        assert parsed.attributes["template"] == "emdr"
        assert parsed.meta.doc_type == "emdr"
        assert parsed.meta.revision is None
        assert parsed.warnings == ()
        assert all(b.kind == "table" for b in parsed.blocks)
        sections = [b.section_path for b in parsed.blocks]
        assert sections == ["Header", "Manufacturer", "Device", "Event"]
        header = parsed.blocks[0]
        assert header.fields["Report Number"] == "EMDR-0001"
        assert header.fields["MDR Record"] == "MDR-0001"
        assert "Report Number: EMDR-0001" in header.text
        event = parsed.blocks[3]
        assert event.fields["Source Complaint"].startswith("C-")
        assert "SOP-007" in event.fields["Reporting Basis"]

    def test_repeated_sibling_paths_are_preserved_not_collapsed(self, tmp_path):
        # Two device-problem-code leaves share a humanized path; a plain dict
        # would keep only the last. The parser must retain both so nothing is
        # silently dropped (the promise the module docstring makes).
        xml = (
            '<?xml version="1.0"?>'
            "<emdr><event>"
            "<device-problem-code>1234</device-problem-code>"
            "<device-problem-code>5678</device-problem-code>"
            "<event-narrative>Two coded problems observed.</event-narrative>"
            "</event></emdr>"
        )
        path = tmp_path / "EMDR-9999.xml"
        path.write_text(xml, encoding="utf-8")
        meta = DocMeta(doc_key="EMDR-9999", doc_type="emdr", title="eMDR", file_format="xml")
        parsed = XmlFormParser().parse(path, meta)
        fields = parsed.blocks[0].fields
        assert fields["Device Problem Code"] == "1234"
        assert fields["Device Problem Code 2"] == "5678"
        assert "1234" in parsed.blocks[0].text
        assert "5678" in parsed.blocks[0].text


class TestXlsxGrid:
    def test_training_matrix_rows(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "09_training/TRN-100_Training_Matrix.xlsx")
        assert parsed.attributes["template"] == "training_grid"
        assert parsed.meta.revision
        rows = [b for b in parsed.blocks if b.kind == "row"]
        assert rows
        first = rows[0]
        assert "Employee" in first.fields
        doc_columns = [key for key in first.fields if key != "Employee"]
        assert doc_columns
        assert all(first.fields[key].startswith("Rev ") for key in doc_columns)
        assert first.section_path.startswith("training row ")

    def test_blank_header_column_preserves_document_mapping(self, tmp_path):
        # A blank column sits between two document columns. Compressing the header
        # and zipping against raw row cells would shift Rev C off SOP-012; column
        # indexes must be preserved so each completion lands on the right document.
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Training Matrix"
        ws.append(["Employee", "SOP-004", None, "SOP-012"])
        ws.append(["Alice Adams (QA)", "Rev B 14-Mar-2025", None, "Rev C 20-Mar-2025"])
        path = tmp_path / "TRN-998_blank_header_col.xlsx"
        wb.save(str(path))
        meta = DocMeta(doc_key="TRN-998", doc_type="training", title="Training", file_format="xlsx")

        parsed = XlsxGridParser().parse(path, meta)
        row = parsed.blocks[0]
        assert row.fields["SOP-004"] == "Rev B 14-Mar-2025"
        assert row.fields["SOP-012"] == "Rev C 20-Mar-2025"
        assert parsed.attributes["doc_columns"] == "SOP-004, SOP-012"

    def test_multi_sheet_workbook_rejected(self, tmp_path):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Training Matrix"
        ws.append(["Employee", "SOP-004"])
        ws.append(["Alice Adams (QA)", "Rev B 14-Mar-2025"])
        wb.create_sheet("Second Sheet")
        path = tmp_path / "TRN-997_two_sheets.xlsx"
        wb.save(str(path))
        meta = DocMeta(doc_key="TRN-997", doc_type="training", title="Training", file_format="xlsx")
        with pytest.raises(ParseError, match="worksheets"):
            XlsxGridParser().parse(path, meta)


class TestSupplierList:
    def test_supplier_rows(self, router, corpus_dir):
        parsed = _parse(router, corpus_dir, "07_suppliers/ASL-100_Approved_Supplier_List.xlsx")
        assert parsed.attributes["template"] == "supplier_list"
        rows = [b for b in parsed.blocks if b.kind == "row"]
        assert rows
        assert rows[0].fields["Supplier ID"].startswith("SUP-")
        assert rows[0].fields["Approval Status"]


class TestRouter:
    def test_scanned_dhr_routes_to_ocr_parser(self, router, corpus_dir):
        route = router.route(corpus_dir / "08_production_records/DHR_L250007_scanned.pdf")
        assert route.parser is not None
        assert route.parser.name == "pdf_scanned"

    def test_training_matrix_routes_to_grid_parser(self, router, corpus_dir):
        route = router.route(corpus_dir / "09_training/TRN-100_Training_Matrix.xlsx")
        assert route.parser is not None
        assert route.parser.name == "xlsx_grid"

    def test_whole_corpus_routes(self, router, corpus_dir):
        files = sorted(p for p in corpus_dir.rglob("*") if p.is_file())
        assert len(files) > 180
        for path in files:
            route = router.route(path)  # raises UnrecognizedDocumentError on failure
            assert route.parser is not None, route.skip_reason
