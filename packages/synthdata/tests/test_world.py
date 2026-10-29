"""World construction: determinism, cross-reference integrity, seeded defects."""

from gg_synthdata import ids
from gg_synthdata.sop_content import ALL_PROCEDURES
from gg_synthdata.world import build_world


def test_same_seed_same_world():
    assert build_world(42) == build_world(42)


def test_different_seed_different_world():
    assert build_world(42) != build_world(7)


def test_cross_references_resolve():
    world = build_world(42)
    capa_ids = {c.capa_id for c in world.capas}
    ncr_ids = {n.ncr_id for n in world.ncrs}
    complaint_ids = {c.complaint_id for c in world.complaints}
    supplier_ids = {s.supplier_id for s in world.suppliers}

    for ncr in world.ncrs:
        if ncr.capa_id:
            assert ncr.capa_id in capa_ids
        if ncr.supplier_id:
            assert ncr.supplier_id in supplier_ids
    for capa in world.capas:
        if capa.source_type == "ncr":
            assert capa.source_id in ncr_ids
        elif capa.source_type == "complaint":
            assert capa.source_id in complaint_ids
    for mdr in world.mdrs:
        assert mdr.complaint_id in complaint_ids
    for complaint in world.complaints:
        if complaint.mdr_id:
            assert any(m.mdr_id == complaint.mdr_id for m in world.mdrs)
    for component in world.components:
        if component.supplier_id:
            assert component.supplier_id in supplier_ids
    for doc in world.controlled_docs:
        for ref in doc.references:
            assert ref in world.doc_index or ref.startswith(("TM-", "DFMEA-", "PFMEA-"))


def test_internal_audits_cover_every_cited_audit_id():
    world = build_world(42)
    audits = {a.audit_id: a for a in world.internal_audits}
    cited = {c.source_id for c in world.capas if c.source_type == "internal_audit"}
    assert cited
    assert cited <= set(audits)
    for capa in world.capas:
        if capa.source_type != "internal_audit":
            continue
        audit = audits[capa.source_id]
        assert capa.capa_id in audit.capa_ids
        assert audit.audit_date <= capa.opened
    for audit in world.internal_audits:
        assert set(audit.scope_docs) <= set(world.doc_index) | {"ASL-100"}


def test_management_reviews_summarize_their_period():
    world = build_world(42)
    audit_ids = {a.audit_id for a in world.internal_audits}
    for review in world.management_reviews:
        assert review.period_start < review.period_end < review.meeting_date
        assert set(review.audit_ids) <= audit_ids
        for audit_id in review.audit_ids:
            audit = next(a for a in world.internal_audits if a.audit_id == audit_id)
            assert review.period_start <= audit.audit_date <= review.period_end
        assert review.capas_opened == sum(
            1 for c in world.capas if review.period_start <= c.opened <= review.period_end
        )


def test_control_plan_covers_every_pfmea_row():
    world = build_world(42)
    assert world.control_plan_doc.doc_id == "CTL-100"
    assert world.doc_index["CTL-100"] is world.control_plan_doc
    assert [r.pfmea_row for r in world.control_plan_rows] == [r.row_id for r in world.pfmea_rows]
    assert [r.process_step for r in world.control_plan_rows] == [r.item for r in world.pfmea_rows]
    for row in world.control_plan_rows:
        assert row.reference in world.doc_index
        assert row.control_method
        assert row.reaction_plan


def test_pfmea_realization_links_target_valid_dfmea_rows():
    world = build_world(42)
    links = {r.row_id: r.realizes_dfmea_row for r in world.pfmea_rows if r.realizes_dfmea_row}
    assert links == {2: 7, 3: 7, 4: 1}
    assert set(links.values()) <= {r.row_id for r in world.dfmea_rows}
    assert all(r.realizes_dfmea_row is None for r in world.dfmea_rows)


def test_clinical_docs_are_controlled_and_indexed():
    world = build_world(42)
    assert [d.doc_id for d in world.clinical_docs] == ["CIP-100", "CER-100"]
    for doc in world.clinical_docs:
        assert world.doc_index[doc.doc_id] is doc
        dates = [r.rev_date for r in doc.revisions]
        assert dates == sorted(dates), doc.doc_id
        for ref in doc.references:
            assert ref in world.doc_index, f"{doc.doc_id} -> {ref}"


def test_trace_gap_is_exactly_req_017():
    world = build_world(42)
    assert world.trace_gaps == ("REQ-017",)
    covered = {req_id for t in world.verification_tests for req_id in t.req_ids}
    assert "REQ-017" not in covered
    for req in world.requirements:
        if req.req_id != "REQ-017":
            assert req.req_id in covered, f"{req.req_id} lacks verification"


def test_revision_histories_are_ordered():
    world = build_world(42)
    for doc in world.controlled_docs:
        dates = [r.rev_date for r in doc.revisions]
        assert dates == sorted(dates), doc.doc_id
        letters = [r.rev for r in doc.revisions]
        assert letters == [chr(ord("A") + i) for i in range(len(letters))], doc.doc_id
        assert all(d < ids.WORLD_TODAY for d in dates), doc.doc_id


def test_regulation_era_split():
    world = build_world(42)
    spec_by_doc_id = {
        (ids.sop_id(s.number) if s.kind == "sop" else ids.wi_id(s.number)): s
        for s in ALL_PROCEDURES
    }
    pre, post = [], []
    for doc in world.controlled_docs:
        if doc.doc_type not in ("sop", "wi"):
            continue
        spec = spec_by_doc_id[doc.doc_id]
        if doc.current.rev_date >= ids.QMSR_EFFECTIVE:
            post.append(doc)
            assert doc.regulation_refs == spec.iso_refs, doc.doc_id
        else:
            pre.append(doc)
            assert doc.regulation_refs == spec.qsr_refs, doc.doc_id
    assert len(pre) >= 5, "expected a QSR-era subset"
    assert len(post) >= 5, "expected a post-QMSR subset"


def test_seeded_defects_ground_truth():
    world = build_world(42)
    by_kind = {d.kind: d for d in world.defects}
    assert set(by_kind) == {
        "broken_trace_link",
        "ap_mismatch",
        "overdue_effectiveness_check",
        "complaint_without_risk_evaluation",
        "stale_sop_reference",
    }

    capa = next(c for c in world.capas if c.capa_id == "CAPA-2025-007")
    assert capa.status == "open"
    assert capa.effectiveness_completed is None
    assert capa.effectiveness_due < ids.WORLD_TODAY

    complaint = next(c for c in world.complaints if c.complaint_id == "C-2025-0142")
    assert complaint.risk_evaluated is False
    assert complaint.risk_reference is None
    others = [c for c in world.complaints if c.complaint_id != "C-2025-0142"]
    assert all(c.risk_evaluated for c in others)

    mismatch = [r for r in world.dfmea_rows if r.ap_recorded != r.ap_correct]
    assert len(mismatch) == 1
    assert mismatch[0].item == "FT-210 Feedthrough"
    assert (mismatch[0].ap_recorded, mismatch[0].ap_correct) == ("M", "H")
    assert all(r.ap_recorded == r.ap_correct for r in world.pfmea_rows)
