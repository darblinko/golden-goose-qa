"""Generated QA items carry non-leakage expectations: an exact-revision pin
and the prior revision for revision questions, and neighbouring records for
questions about one record. Without them the battery's non-leakage check
had nothing to test."""

from gg_synthdata.qa import QA_SCHEMA_VERSION, build_qa_set
from gg_synthdata.world import build_world


def _items():
    return {item.id: item for item in build_qa_set(build_world(42)).items}


def test_revision_questions_pin_the_current_revision_and_exclude_the_prior():
    world = build_world(42)
    items = [i for i in _items().values() if i.pattern == "revision_approval"]
    sop = next(i for i in items if "SOP-004" in i.question)
    doc = world.doc("SOP-004")
    assert sop.evidence_revisions == {"SOP-004": doc.current.rev}
    assert sop.must_exclude == [f"SOP-004@{doc.revisions[-2].rev}"]
    assert all(i.evidence_revisions for i in items)


def test_single_record_questions_exclude_neighbouring_records():
    items = _items()
    capa = next(i for i in items.values() if "CAPA-2025-014" in i.question)
    assert capa.must_exclude == ["CAPA-2025-011", "CAPA-2026-001"]  # sorted neighbours
    mdr = next(
        i for i in items.values() if i.question.startswith("Which complaint led to MDR-0004")
    )
    assert mdr.must_exclude == ["MDR-0003", "MDR-0005"]
    for item in items.values():
        assert not set(item.must_exclude) & set(item.evidence_doc_ids), item.id


def test_exclusion_coverage_is_not_empty():
    items = list(_items().values())
    assert sum(1 for i in items if i.must_exclude) >= 60
    assert sum(1 for i in items if i.evidence_revisions) >= 37
    assert QA_SCHEMA_VERSION == 3
