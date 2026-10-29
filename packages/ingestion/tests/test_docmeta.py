from pathlib import Path

import pytest
from gg_ingestion.docmeta import UnrecognizedDocumentError, doc_meta_from_path


@pytest.mark.parametrize(
    ("filename", "doc_key", "doc_type", "title"),
    [
        (
            "SOP-004_Corrective_and_Preventive_Action.docx",
            "SOP-004",
            "sop",
            "Corrective and Preventive Action",
        ),
        (
            # Archived revision: the _Rev_X suffix marks the file, never the identity.
            "SOP-004_Corrective_and_Preventive_Action_Rev_A.docx",
            "SOP-004",
            "sop",
            "Corrective and Preventive Action",
        ),
        ("QM-001_Quality_Manual.docx", "QM-001", "quality_manual", "Quality Manual"),
        ("CAPA-2025-007.docx", "CAPA-2025-007", "capa", "CAPA-2025-007"),
        ("NCR-2025-0033.pdf", "NCR-2025-0033", "ncr", "NCR-2025-0033"),
        ("C-2025-0142.pdf", "C-2025-0142", "complaint", "C-2025-0142"),
        ("MDR-2025-0009.pdf", "MDR-2025-0009", "mdr", "MDR-2025-0009"),
        # EMDR must win over the MDR prefix embedded in it.
        ("EMDR-0001.xml", "EMDR-0001", "emdr", "EMDR-0001"),
        ("AUD-2025-01.docx", "AUD-2025-01", "internal_audit", "AUD-2025-01"),
        ("MRM-2025-02.docx", "MRM-2025-02", "management_review", "MRM-2025-02"),
        (
            "CIP-100_Clinical_Investigation_Plan.docx",
            "CIP-100",
            "clinical_plan",
            "Clinical Investigation Plan",
        ),
        (
            "CER-100_Clinical_Evaluation_Report.docx",
            "CER-100",
            "clinical_report",
            "Clinical Evaluation Report",
        ),
        (
            "CTL-100_Process_Control_Plan.xlsx",
            "CTL-100",
            "control_plan",
            "Process Control Plan",
        ),
        (
            "TM-100_Design_Traceability_Matrix.xlsx",
            "TM-100",
            "trace_matrix",
            "Design Traceability Matrix",
        ),
        ("DFMEA-100_Design_FMEA.xlsx", "DFMEA-100", "dfmea", "Design FMEA"),
        ("PFMEA-200_Process_FMEA.xlsx", "PFMEA-200", "pfmea", "Process FMEA"),
        ("TRN-100_Training_Matrix.xlsx", "TRN-100", "training_matrix", "Training Matrix"),
        (
            "VTR-021_Verification_Report.pdf",
            "VTR-021",
            "verification_report",
            "Verification Report",
        ),
    ],
)
def test_key_extraction(filename, doc_key, doc_type, title):
    meta = doc_meta_from_path(Path(filename))
    assert meta.doc_key == doc_key
    assert meta.doc_type == doc_type
    assert meta.title == title
    assert meta.file_format == filename.rsplit(".", 1)[1]


def test_capa_not_swallowed_by_complaint_prefix():
    meta = doc_meta_from_path(Path("CAPA-2025-007.docx"))
    assert meta.doc_type == "capa"
    assert meta.doc_key.startswith("CAPA-")


def test_dhr_lot_extraction():
    meta = doc_meta_from_path(Path("DHR_L24-1002.pdf"))
    assert meta.doc_key == "DHR-L24-1002"
    assert meta.doc_type == "dhr"
    assert "L24-1002" in meta.title


def test_dhr_scanned_variant():
    meta = doc_meta_from_path(Path("DHR_L24-1002_scanned.pdf"))
    assert meta.doc_key == "DHR-L24-1002"
    assert meta.doc_type == "dhr_scanned"


def test_unrecognized_filename_raises():
    with pytest.raises(UnrecognizedDocumentError):
        doc_meta_from_path(Path("meeting_notes.txt"))


def test_every_doc_type_has_an_acl_classification():
    """A new document family must be explicitly classified in gg_common.acl
    before ingestion; otherwise access_level_for fails it closed to
    restricted, which would silently hide general content."""
    from gg_common.acl import KNOWN_GENERAL_DOC_TYPES, RESTRICTED_DOC_TYPES
    from gg_ingestion.docmeta import _DOC_TYPE_BY_PREFIX

    all_types = set(_DOC_TYPE_BY_PREFIX.values()) | {"dhr_scanned"}
    unclassified = all_types - KNOWN_GENERAL_DOC_TYPES - RESTRICTED_DOC_TYPES
    assert not unclassified, f"doc types missing ACL classification: {sorted(unclassified)}"
