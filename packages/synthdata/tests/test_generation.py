"""Full corpus generation: file output, QA schema, parseability, determinism.

This is the heavyweight Phase 1 acceptance test: it generates the corpus once,
then runs `verify`, which re-parses every file and regenerates the corpus to
prove byte-determinism.
"""

import json

import pytest
from gg_synthdata.cli import cmd_generate, cmd_verify
from gg_synthdata.qa import QaSet, build_qa_set
from gg_synthdata.world import build_world


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("corpus")
    assert cmd_generate(out_dir, seed=42) == 0
    return out_dir


def test_manifest_counts(generated):
    manifest = json.loads((generated / "manifest.json").read_text())
    assert manifest["seed"] == 42
    assert manifest["counts"]["files"] > 180
    assert manifest["counts"]["qa_items"] >= 150
    assert manifest["counts"]["qa_smoke_items"] == 30
    assert manifest["counts"]["seeded_defects"] == 5


def test_expected_documents_exist(generated):
    corpus = generated / "corpus"
    expected = (
        "01_quality_system/QM-001_Quality_Manual.docx",
        "01_quality_system/SOP-004_Corrective_and_Preventive_Action.docx",
        "02_design_history_file/TM-100_Design_Traceability_Matrix.xlsx",
        "03_risk_management/DFMEA-100_Design_FMEA.xlsx",
        "04_capa/CAPA-2025-007.docx",
        "06_complaints/C-2025-0142.pdf",
        "09_training/TRN-100_Training_Matrix.xlsx",
    )
    for rel in expected:
        assert (corpus / rel).exists(), rel
    scanned = list((corpus / "08_production_records").glob("*_scanned.pdf"))
    assert len(scanned) == 3
    archived = list((corpus / "01_quality_system" / "archive").glob("*_Rev_*.docx"))
    assert archived, "multi-revision procedures must archive their prior revision"
    assert (
        corpus / "01_quality_system/archive/SOP-004_Corrective_and_Preventive_Action_Rev_A.docx"
    ).exists()
    emdrs = list((corpus / "10_regulatory").glob("EMDR-*.xml"))
    assert emdrs, "every MDR must have an eMDR electronic submission export"
    assert (corpus / "10_regulatory/EMDR-0001.xml").exists()
    audits = sorted((corpus / "11_internal_audit").glob("AUD-*.docx"))
    assert len(audits) == 6, "two internal audits per year, 2024 through 2026"
    reviews = sorted((corpus / "12_management_review").glob("MRM-*.docx"))
    assert len(reviews) == 4, "semiannual management reviews through 2025 H2"
    assert (corpus / "13_clinical/CIP-100_Clinical_Investigation_Plan.docx").exists()
    assert (corpus / "13_clinical/CER-100_Clinical_Evaluation_Report.docx").exists()
    assert (corpus / "03_risk_management/CTL-100_Process_Control_Plan.xlsx").exists()


def test_verify_passes(generated):
    assert cmd_verify(generated) == 0


def test_verify_detects_tampering(generated, capsys):
    target = generated / "corpus" / "06_complaints" / "C-2025-0142.pdf"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b" ")
        assert cmd_verify(generated) == 1
        assert "C-2025-0142.pdf" in capsys.readouterr().err
    finally:
        target.write_bytes(original)


def test_qa_set_schema_and_evidence():
    world = build_world(42)
    qa_set = build_qa_set(world)
    QaSet.model_validate(qa_set.model_dump())
    assert qa_set.schema_version >= 2
    assert len(qa_set.items) >= 150
    patterns = {i.pattern for i in qa_set.items}
    assert len(patterns) == 12
    assert sum(1 for i in qa_set.items if i.smoke) == 30
    # Every pattern is represented in the smoke subset (no whole pattern dropped).
    assert {i.pattern for i in qa_set.items if i.smoke} == patterns

    record_ids = (
        {c.capa_id for c in world.capas}
        | {n.ncr_id for n in world.ncrs}
        | {c.complaint_id for c in world.complaints}
        | {m.mdr_id for m in world.mdrs}
    )
    for item in qa_set.items:
        # An item must have some evidence, and every item must carry routes.
        assert item.evidence_doc_ids or item.answer_source_ids, item.id
        assert item.expected_routes, item.id
        # Non-document identifiers live in answer_source_ids, never evidence.
        for evidence in item.evidence_doc_ids:
            assert not evidence.startswith(("corpus:", "REQ-")), f"{item.id}: {evidence}"
            if evidence.startswith(("CAPA-", "NCR-", "MDR-")) or (
                evidence.startswith("C-") and evidence.count("-") == 2
            ):
                assert evidence in record_ids, f"{item.id}: {evidence}"


def test_defect_questions_are_smoke_and_hard():
    qa_set = build_qa_set(build_world(42))
    defect_items = [i for i in qa_set.items if i.pattern == "defect_discovery"]
    assert len(defect_items) >= 7
    assert all(i.difficulty == "hard" for i in defect_items)
    assert sum(1 for i in defect_items if i.smoke) == 5


def test_smoke_set_is_exactly_30_unique_subset_of_golden():
    from gg_synthdata.qa import SMOKE_SET_SIZE, SmokeQaSet, build_smoke_set

    qa_set = build_qa_set(build_world(42))
    smoke = build_smoke_set(qa_set)
    SmokeQaSet.model_validate(smoke.model_dump())  # its own schema, not QaSet's
    assert len(smoke.items) == SMOKE_SET_SIZE == 30
    ids = [i.id for i in smoke.items]
    assert len(set(ids)) == len(ids), "smoke ids must be unique"
    golden_by_id = {i.id: i for i in qa_set.items}
    for item in smoke.items:
        assert golden_by_id[item.id] == item, f"{item.id} diverges from golden"
    assert {i.pattern for i in smoke.items} == {i.pattern for i in qa_set.items}


def test_verify_rejects_a_tampered_smoke_set(generated, capsys):
    smoke_path = generated / "qa" / "smoke_qa.json"
    original = smoke_path.read_text()
    try:
        data = json.loads(original)
        data["items"] = data["items"][:-1]  # 29 items — no longer the promised 30
        smoke_path.write_text(json.dumps(data, indent=2) + "\n")
        assert cmd_verify(generated) == 1
        assert "smoke_qa.json" in capsys.readouterr().err
    finally:
        smoke_path.write_text(original)


def test_pdf_content_check_passes_real_pdfs(generated):
    from gg_synthdata.cli import _check_parseable

    digital = generated / "corpus" / "06_complaints" / "C-2025-0142.pdf"
    assert _check_parseable(digital) is None  # digital record has extractable text
    scanned = next((generated / "corpus" / "08_production_records").glob("*_scanned.pdf"))
    assert _check_parseable(scanned) is None  # scanned record embeds an image


def test_pdf_check_not_fooled_by_magic_bytes(tmp_path):
    from gg_synthdata.cli import _check_parseable

    # The old check keyed only on a %PDF prefix and a trailing %%EOF; a gutted
    # file with both must now fail because pypdf cannot enumerate a real page.
    fake = tmp_path / "gutted.pdf"
    fake.write_bytes(b"%PDF-1.7\n" + b"garbage line\n" * 20 + b"%%EOF")
    assert _check_parseable(fake) is not None


def test_trace_matrix_has_grouped_header_and_category_merges(generated):
    from openpyxl import load_workbook

    path = (
        generated / "corpus" / "02_design_history_file" / "TM-100_Design_Traceability_Matrix.xlsx"
    )
    ws = load_workbook(path).active
    merges = {str(r) for r in ws.merged_cells.ranges}
    # Grouped header band on row 3 above the flat field-header row on row 4.
    assert "A3:C3" in merges  # Requirement group
    assert "E3:G3" in merges  # Verification group
    assert ws.cell(row=4, column=1).value == "Requirement ID"
    assert ws.cell(row=5, column=1).value == "REQ-001"
    # REQ-001..REQ-005 are one electrical run rendered as a vertical Category
    # merge (rows 5-9), with the continuation cells cleared.
    assert "B5:B9" in merges
    assert ws.cell(row=5, column=2).value == "electrical"
    assert ws.cell(row=6, column=2).value is None
