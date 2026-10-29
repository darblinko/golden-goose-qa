"""Extraction tests against the full synthetic corpus (seed 42).

A session-scoped fixture parses and extracts every parseable corpus file so
individual tests assert on extraction output while the corpus-wide contract
(register columns, edge whitelists, no dangling refs) is checked in one pass.
"""

import asyncio
from datetime import date

import pytest
from gg_common.providers.fakes import FakeOCRProvider
from gg_ingestion.extract.extractors import extract_document
from gg_ingestion.extract.graph_load import edge_query
from gg_ingestion.extract.model import DocExtraction
from gg_ingestion.extract.records import RecordExtractionError
from gg_ingestion.extract.warehouse_load import validate_row
from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument
from gg_ingestion.parsers.base import AsyncDocumentParser
from gg_ingestion.parsers.router import ParserRouter


def _ncr_document(date_closed: str) -> ParsedDocument:
    """A minimal closed-NCR PDF form whose only variable is its Date Closed."""
    page = (
        "Nonconforming Product Report — NCR-2099-001\n"
        "NCR Number\nNCR-2099-001\n"
        "Date Opened\n12-Feb-2025\n"
        "Part Number\nCG-3000 — Titanium Enclosure\n"
        "Supplier\nApex (SUP-004)\n"
        "Description of Nonconformance\nDimensional nonconformance at incoming.\n"
        "Disposition\nrework\n"
        "Linked CAPA\nNone\n"
        "Status\nClosed\n"
        f"Date Closed\n{date_closed}\n"
        "Dispositioned per WI-104.\n"
    )
    return ParsedDocument(
        meta=DocMeta(doc_key="NCR-2099-001", doc_type="ncr", title="NCR", file_format="pdf"),
        blocks=(ParsedBlock(kind="page", text=page, page=1),),
        parser="pdf_form",
    )


def test_closed_record_extracts_its_close_date():
    extraction = extract_document(_ncr_document("14-Jun-2025"), frozenset())
    (row,) = extraction.register_rows
    assert row.values["closed"] == date(2025, 6, 14)


def test_malformed_close_date_fails_loud_never_registers_open():
    # A corrupt Date Closed must raise, not silently drop to None — a None close
    # date is what the registers read as is_open, so swallowing it would turn a
    # closed record into a phantom open one and inflate open-record counts.
    with pytest.raises(RecordExtractionError, match="unparseable date"):
        extract_document(_ncr_document("2025-06-14"), frozenset())


@pytest.fixture(scope="session")
def extractions(corpus_dir) -> dict[str, DocExtraction]:
    router = ParserRouter(ocr=FakeOCRProvider())
    # Archived (superseded) revisions share their doc_key with the effective
    # revision and never feed the graph or registers — mirroring the derive
    # pass, which projects only the currently effective version.
    routes = [
        (path, router.route(path))
        for path in sorted(corpus_dir.rglob("*"))
        if path.is_file() and "archive" not in path.parent.parts
    ]
    known = frozenset(route.meta.doc_key for _, route in routes)
    result: dict[str, DocExtraction] = {}
    for path, route in routes:
        if route.parser is None:
            continue
        if isinstance(route.parser, AsyncDocumentParser):
            parsed = asyncio.run(route.parser.parse(path, route.meta))
        else:
            parsed = route.parser.parse(path, route.meta)
        result[route.meta.doc_key] = extract_document(parsed, known)
    return result


def _edges(extraction: DocExtraction, rel_type: str):
    return [e for e in extraction.edges if e.rel_type == rel_type]


class TestCorpusContract:
    def test_register_rows_match_warehouse_columns(self, extractions):
        for extraction in extractions.values():
            for row in extraction.register_rows:
                validate_row(row)

    def test_edges_use_whitelisted_labels_and_types(self, extractions):
        for extraction in extractions.values():
            for edge in extraction.edges:
                assert edge_query(edge.rel_type, edge.start_label, edge.end_label)
                assert edge.provenance.doc_key == extraction.doc_key
                assert 0.0 < edge.provenance.confidence <= 1.0

    def test_no_dangling_refs_or_warnings_in_corpus(self, extractions):
        dangling = {k: e.dangling_refs for k, e in extractions.items() if e.dangling_refs}
        warnings = {k: e.warnings for k, e in extractions.items() if e.warnings}
        assert dangling == {}
        assert warnings == {}


class TestTraceMatrix:
    def test_requirements_and_verifies_edges(self, extractions):
        tm = extractions["TM-100"]
        requirements = [n for n in tm.nodes if n.label == "Requirement"]
        assert len(requirements) == 40
        verifies = _edges(tm, "VERIFIES")
        assert verifies
        assert all(e.start_label == "Document" and e.end_label == "Requirement" for e in verifies)
        assert any(e.properties.get("protocol_id", "").startswith("VTP-") for e in verifies)
        satisfies = _edges(tm, "SATISFIES")
        assert all(e.start_label == "DesignOutput" for e in satisfies)

    def test_req_017_verification_gap(self, extractions):
        tm = extractions["TM-100"]
        assert not [e for e in _edges(tm, "VERIFIES") if e.end_key == "REQ-017"]
        row = next(r for r in tm.register_rows if r.values["req_id"] == "REQ-017")
        assert row.values["has_verification"] is False
        covered = next(r for r in tm.register_rows if r.values["req_id"] == "REQ-001")
        assert covered.values["has_verification"] is True

    def test_requirement_nodes_retain_source_document_and_locator(self, extractions):
        # The graph must be able to cite where each requirement was read from,
        # so a "no verification" finding names an exact document and row.
        tm = extractions["TM-100"]
        req_017 = next(n for n in tm.nodes if n.label == "Requirement" and n.key == "REQ-017")
        assert req_017.properties["source_doc_key"] == "TM-100"
        assert req_017.properties["locator"].startswith("row ")


class TestFmea:
    def test_row_nodes_recompute_action_priority(self, extractions):
        dfmea = extractions["DFMEA-100"]
        rows = [n for n in dfmea.nodes if n.label == "FmeaRow"]
        assert rows
        assert len(_edges(dfmea, "HAS_ROW")) == len(rows)
        seeded = next(n for n in rows if n.key == "DFMEA-100:3")
        assert seeded.properties["ap_recorded"] == "M"
        assert seeded.properties["ap_computed"] == "H"
        assert seeded.properties["ap_mismatch"] is True

    def test_only_seeded_mismatch_in_corpus(self, extractions):
        mismatches = [
            row.values
            for extraction in extractions.values()
            for row in extraction.register_rows
            if row.table == "fmea_row" and row.values["ap_mismatch"]
        ]
        assert [(m["doc_key"], m["row_id"]) for m in mismatches] == [("DFMEA-100", 3)]

    def test_mitigated_by_targets_risk_file(self, extractions):
        dfmea = extractions["DFMEA-100"]
        mitigated = _edges(dfmea, "MITIGATED_BY")
        assert mitigated
        assert {e.end_key for e in mitigated} == {"RA-100"}

    def test_pfmea_rows_realize_dfmea_failure_modes(self, extractions):
        realized = _edges(extractions["PFMEA-100"], "REALIZED_IN")
        assert {(e.start_key, e.end_key) for e in realized} == {
            ("DFMEA-100:7", "PFMEA-100:2"),
            ("DFMEA-100:7", "PFMEA-100:3"),
            ("DFMEA-100:1", "PFMEA-100:4"),
        }
        assert all(e.provenance.method == "fmea_sheet" for e in realized)
        assert _edges(extractions["DFMEA-100"], "REALIZED_IN") == []

    def test_control_plan_pins_every_pfmea_row(self, extractions):
        ctl = extractions["CTL-100"]
        controlled = _edges(ctl, "CONTROLLED_BY")
        pfmea_rows = {n.key for n in extractions["PFMEA-100"].nodes if n.label == "FmeaRow"}
        assert pfmea_rows
        assert {e.start_key for e in controlled} == pfmea_rows
        assert all(e.end_key == "CTL-100" for e in controlled)
        assert all(e.provenance.method == "control_plan" for e in controlled)
        for edge in controlled:
            assert edge.properties["characteristic"]
            assert edge.properties["control_method"]
        references = {e.end_key for e in _edges(ctl, "REFERENCES")}
        assert "WI-102" in references
        # The FMEA register stays the system of record for process risk rows.
        assert ctl.register_rows == ()


class TestSupplierAndTraining:
    def test_supplier_list_nodes_and_audit_edges(self, extractions):
        asl = extractions["ASL-100"]
        suppliers = [n for n in asl.nodes if n.label == "Supplier"]
        assert suppliers
        assert len(_edges(asl, "LISTS")) == len(suppliers)
        audits = _edges(asl, "AUDITS")
        assert audits
        assert all(e.start_key.startswith("ASR-") for e in audits)
        row = next(r for r in asl.register_rows if r.values["supplier_id"] == suppliers[0].key)
        assert row.values["name"]

    def test_training_grid_edges_carry_revision_and_date(self, extractions):
        trn = extractions["TRN-100"]
        people = [n for n in trn.nodes if n.label == "Person"]
        assert people
        assert all(n.properties["role"] for n in people)
        trained = _edges(trn, "TRAINED_ON")
        assert trained
        for edge in trained:
            assert edge.properties["revision"]
            assert edge.properties["trained_on"]
        assert all(r.values["source_doc_key"] == "TRN-100" for r in trn.register_rows)


class TestRecords:
    def test_capa_sourced_from_edges(self, extractions):
        capas = [e for e in extractions.values() if e.doc_type == "capa"]
        assert capas
        sourced = [e for capa in capas for e in _edges(capa, "SOURCED_FROM")]
        assert sourced
        internal = [
            row.values
            for capa in capas
            for row in capa.register_rows
            if row.values["source_type"] == "internal audit"
        ]
        assert internal
        # Every internal-audit CAPA links to its source audit report.
        sourced_by_capa = {e.provenance.doc_key: e.end_key for e in sourced}
        for values in internal:
            assert values["source_id"].startswith("AUD-")
            assert sourced_by_capa[values["capa_id"]] == values["source_id"]
            assert extractions[values["source_id"]].doc_type == "internal_audit"

    def test_ncr_escalation_and_supplier(self, extractions):
        ncrs = [e for e in extractions.values() if e.doc_type == "ncr"]
        assert ncrs
        assert any(_edges(n, "ESCALATED_TO") for n in ncrs)
        assert any(_edges(n, "FROM_SUPPLIER") for n in ncrs)
        for ncr in ncrs:
            row = next(r for r in ncr.register_rows if r.table == "ncr")
            assert row.values["part_number"]
            assert "—" not in row.values["part_number"]

    def test_complaint_mdr_chain(self, extractions):
        complaints = [e for e in extractions.values() if e.doc_type == "complaint"]
        mdrs = [e for e in extractions.values() if e.doc_type == "mdr"]
        assert complaints and mdrs
        filed = [e for c in complaints for e in _edges(c, "FILED_AS")]
        assert filed
        from_complaint = [e for m in mdrs for e in _edges(m, "FROM_COMPLAINT")]
        assert from_complaint
        assert {e.end_key for e in filed} == {e.provenance.doc_key for e in from_complaint}
        evaluated = [e for c in complaints for e in _edges(c, "EVALUATED_AGAINST")]
        assert evaluated
        assert all(e.end_key.startswith("RA-") for e in evaluated)

    def test_emdr_submission_linkage(self, extractions):
        emdrs = [e for e in extractions.values() if e.doc_type == "emdr"]
        mdr_keys = {e.doc_key for e in extractions.values() if e.doc_type == "mdr"}
        assert emdrs
        for emdr in emdrs:
            submission = _edges(emdr, "SUBMISSION_OF")
            assert len(submission) == 1
            assert submission[0].end_key in mdr_keys
            from_complaint = _edges(emdr, "FROM_COMPLAINT")
            assert len(from_complaint) == 1
            assert from_complaint[0].end_key.startswith("C-")
            # The MDR record stays the register's system of record.
            assert emdr.register_rows == ()

    def test_internal_audit_scope_edges(self, extractions):
        audits = [e for e in extractions.values() if e.doc_type == "internal_audit"]
        assert audits
        for audit in audits:
            scoped = _edges(audit, "AUDITS")
            assert scoped
            assert all(e.provenance.method == "form_field" for e in scoped)
            references = {e.end_key for e in _edges(audit, "REFERENCES")}
            assert "SOP-014" in references
            # Governance records contribute graph linkage only.
            assert audit.register_rows == ()

    def test_management_review_covers_period_audits(self, extractions):
        reviews = [e for e in extractions.values() if e.doc_type == "management_review"]
        audit_keys = {e.doc_key for e in extractions.values() if e.doc_type == "internal_audit"}
        assert reviews
        for review in reviews:
            reviewed = _edges(review, "REVIEWED")
            assert reviewed
            assert {e.end_key for e in reviewed} <= audit_keys
            references = {e.end_key for e in _edges(review, "REFERENCES")}
            assert "SOP-015" in references
            assert review.register_rows == ()

    def test_verification_report_verifies_requirements(self, extractions):
        vtrs = [e for e in extractions.values() if e.doc_type == "verification_report"]
        assert vtrs
        for vtr in vtrs:
            verifies = _edges(vtr, "VERIFIES")
            assert verifies
            assert all(e.end_key.startswith("REQ-") for e in verifies)
            assert all(e.properties.get("protocol_id") for e in verifies)


class TestNarrative:
    def test_sop_revision_history_and_supersedes(self, extractions):
        sop = extractions["SOP-004"]
        revisions = [n for n in sop.nodes if n.label == "DocumentRevision"]
        assert {n.key for n in revisions} == {"SOP-004:A", "SOP-004:B"}
        supersedes = _edges(sop, "SUPERSEDES")
        assert len(supersedes) == 1
        assert supersedes[0].start_key == "SOP-004:B"
        assert supersedes[0].end_key == "SOP-004:A"
        assert len(_edges(sop, "HAS_REVISION")) == 2

    def test_sop_016_stale_reference_becomes_edge(self, extractions):
        sop = extractions["SOP-016"]
        references = _edges(sop, "REFERENCES")
        assert "WI-101" in {e.end_key for e in references}

    def test_sop_016_stale_reference_carries_cited_revision(self, extractions):
        """The seeded DEF-005 citation ("WI-101, ..., Rev A") must survive
        extraction so the stale-references audit gate can compare it against
        WI-101's current revision in the graph."""
        sop = extractions["SOP-016"]
        wi_edges = [e for e in _edges(sop, "REFERENCES") if e.end_key == "WI-101"]
        assert wi_edges
        assert wi_edges[0].properties.get("cited_revision") == "A"

    def test_references_without_rev_text_carry_no_cited_revision(self, extractions):
        sop = extractions["SOP-012"]
        wi_edges = [e for e in _edges(sop, "REFERENCES") if e.end_key == "WI-101"]
        assert wi_edges
        assert "cited_revision" not in wi_edges[0].properties

    def test_clinical_docs_carry_revisions_and_risk_file_refs(self, extractions):
        cip = extractions["CIP-100"]
        cer = extractions["CER-100"]
        for extraction in (cip, cer):
            assert [n for n in extraction.nodes if n.label == "DocumentRevision"]
            assert extraction.register_rows == ()
        assert {"RA-100", "RMP-100"} <= {e.end_key for e in _edges(cip, "REFERENCES")}
        assert {"CIP-100", "RMR-100"} <= {e.end_key for e in _edges(cer, "REFERENCES")}

    def test_self_references_suppressed(self, extractions):
        for extraction in extractions.values():
            for edge in _edges(extraction, "REFERENCES"):
                assert edge.end_key != extraction.doc_key
