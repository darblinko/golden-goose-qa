"""Golden QA generation: questions and answers derived from the World.

Because questions are computed from the same objects the renderers consume,
every answer and evidence pointer is correct by construction. The set covers
the twelve audit query patterns the retrieval evals exercise, including the
five seeded defects.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from gg_synthdata import ids
from gg_synthdata.model import World
from gg_synthdata.render.common import fmt_date

# Bumped whenever the QA item shape changes so the nightly battery can reject a
# stale dashboard restored from an older schema. v2 split non-document
# identifiers out of evidence_doc_ids and added per-item expected_routes. v3
# added must_exclude and evidence_revisions.
QA_SCHEMA_VERSION = 3

Pattern = Literal[
    "revision_approval",
    "procedure_content",
    "trace_walk",
    "fmea_risk",
    "capa_thread",
    "complaint_mdr",
    "counts_aggregates",
    "training",
    "supplier",
    "defect_discovery",
    "regulatory_crosswalk",
    "governance_clinical",
]

# The PR smoke gate is a fixed 30-item subset of the golden set: small enough to
# run on every PR, broad enough to touch all twelve patterns. Keep the quotas
# summing to exactly SMOKE_SET_SIZE.
SMOKE_SET_SIZE = 30

# Number of each pattern's leading questions promoted into the smoke subset.
# Every pattern gets at least 2 so no whole pattern is silently dropped; the
# three core record/trace threads and the five seeded defects get more. The
# values must sum to SMOKE_SET_SIZE.
_SMOKE_QUOTA: dict[str, int] = {
    "revision_approval": 2,
    "procedure_content": 2,
    "trace_walk": 3,
    "fmea_risk": 2,
    "capa_thread": 3,
    "complaint_mdr": 3,
    "counts_aggregates": 2,
    "training": 2,
    "supplier": 2,
    "defect_discovery": 5,
    "regulatory_crosswalk": 2,
    "governance_clinical": 2,
}

assert sum(_SMOKE_QUOTA.values()) == SMOKE_SET_SIZE, "smoke quotas must sum to SMOKE_SET_SIZE"

# Deterministic routes that reach a node able to answer each pattern, emitted
# per item so the routing eval reads intent from the generator rather than a
# hand-maintained table. governance_clinical deliberately excludes `aggregate`:
# the management-review "how many CAPAs were opened" questions route to
# aggregate on count phrasing but are answered from the review record, so they
# misroute and must show red until the composite record+count path lands. The
# gate is not relaxed to hide a genuine misroute.
_PATTERN_ROUTES: dict[str, tuple[str, ...]] = {
    "revision_approval": ("revision", "record", "trace"),
    "procedure_content": ("procedure", "record"),
    "trace_walk": ("trace",),
    "fmea_risk": ("fmea", "record"),
    "capa_thread": ("record", "aggregate"),
    "complaint_mdr": ("record", "aggregate", "external"),
    "counts_aggregates": ("aggregate",),
    "training": ("trace",),
    "supplier": ("record", "aggregate", "trace"),
    "defect_discovery": ("record", "procedure", "trace", "aggregate"),
    "regulatory_crosswalk": ("procedure", "record", "external"),
    "governance_clinical": ("record",),
}

# Evidence identifiers that justify an answer but are not retrievable documents:
# corpus:* aggregate pseudo-ids answered by the record warehouse, and REQ-* rows
# that live inside TM-100 rather than as their own document. They belong in
# answer_source_ids so the retrieval gate never counts a warehouse answer as a
# retrieval target; evidence_doc_ids holds document identifiers only.
_NON_DOCUMENT_PREFIXES = ("corpus:", "REQ-")


def _split_evidence(evidence: list[str]) -> tuple[list[str], list[str]]:
    """Partition raw evidence into retrievable document keys and non-document
    answer sources, preserving order within each."""
    docs: list[str] = []
    sources: list[str] = []
    for ev in evidence:
        (sources if ev.startswith(_NON_DOCUMENT_PREFIXES) else docs).append(ev)
    return docs, sources


class QaItem(BaseModel):
    id: str
    question: str
    answer: str
    pattern: Pattern
    evidence_doc_ids: list[str] = Field(default_factory=list)  # retrievable documents only
    answer_source_ids: list[str] = Field(default_factory=list)  # registers / TM-100 rows
    expected_routes: list[str] = Field(min_length=1)  # routes that can answer this item
    # Doc keys or "DOC-KEY@REVISION" that must not surface for this question.
    must_exclude: list[str] = Field(default_factory=list)
    evidence_revisions: dict[str, str] = Field(default_factory=dict)  # doc key -> revision
    smoke: bool = False
    difficulty: Literal["easy", "medium", "hard"]

    @model_validator(mode="after")
    def _needs_some_evidence(self) -> "QaItem":
        if not self.evidence_doc_ids and not self.answer_source_ids:
            raise ValueError(f"{self.id}: needs an evidence_doc_id or an answer_source_id")
        return self


class QaSet(BaseModel):
    schema_version: int
    seed: int
    world_today: str
    company: str
    items: list[QaItem] = Field(min_length=150)


class SmokeQaSet(BaseModel):
    """Schema for the emitted PR smoke set. It is separate from QaSet — which
    requires the full >=150 items — so the CLI can validate the smoke file
    instead of merely json-loading it. The exact-size and uniqueness rules live
    here; the subset-of-golden check lives in the verifier, which has both files.
    """

    schema_version: int
    seed: int
    world_today: str
    company: str
    items: list[QaItem]

    @model_validator(mode="after")
    def _exactly_sized_and_unique(self) -> "SmokeQaSet":
        if len(self.items) != SMOKE_SET_SIZE:
            raise ValueError(
                f"smoke set must have exactly {SMOKE_SET_SIZE} items, got {len(self.items)}"
            )
        unique_ids = {item.id for item in self.items}
        if len(unique_ids) != len(self.items):
            raise ValueError("smoke set item ids must be unique")
        return self


def build_smoke_set(qa_set: QaSet) -> SmokeQaSet:
    """The smoke-flagged items of a full set, as a validated SmokeQaSet."""
    return SmokeQaSet(
        schema_version=qa_set.schema_version,
        seed=qa_set.seed,
        world_today=qa_set.world_today,
        company=qa_set.company,
        items=[item for item in qa_set.items if item.smoke],
    )


def _revision_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    out = []
    for doc in world.controlled_docs:
        current = doc.current
        out.append(
            (
                f"What is the current revision of {doc.doc_id} ({doc.title}), and who approved it?",
                f"{doc.doc_id} is at Revision {current.rev}, effective "
                f"{fmt_date(current.rev_date)}, approved by {current.approver}.",
                [doc.doc_id],
                "easy",
            )
        )
    return out


def _content_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    return [
        (
            "What is the helium leak acceptance criterion for the enclosure weld?",
            "Per WI-103, the helium leak test acceptance criterion is 1e-9 atm-cc/s.",
            ["WI-103"],
            "easy",
        ),
        (
            "What is the minimum wire bond pull strength and how often are pull tests performed?",
            "Per WI-102, first-article pull tests are performed each shift with a "
            "minimum pull strength of 8 gf, recorded on the traveler.",
            ["WI-102"],
            "easy",
        ),
        (
            "Can a CAPA be closed before its effectiveness check is complete?",
            "No. SOP-004 requires an effectiveness check with objective criteria "
            "and a due date; a CAPA may not close until effectiveness is confirmed.",
            ["SOP-004"],
            "easy",
        ),
        (
            "What does the complaint handling procedure require regarding the risk "
            "management file?",
            "SOP-006 requires each complaint to be evaluated against the risk "
            "management file per SOP-003, with the risk file reference recorded on "
            "the complaint record.",
            ["SOP-006"],
            "easy",
        ),
        (
            "Which procedure governs control of nonconforming product?",
            "SOP-005 governs nonconforming product control; dispositions include "
            "use-as-is, rework, scrap, and return to vendor.",
            ["SOP-005"],
            "easy",
        ),
        (
            "Who is the management representative and where is that designation documented?",
            "The Quality Manual QM-001 designates the Director of Quality "
            "Assurance as management representative, appointed by the President.",
            ["QM-001"],
            "medium",
        ),
        (
            "What sterility assurance level is required and how is sterilization released?",
            "The device is sterilized to SAL 1e-6; per WI-101 loads are released "
            "using biological indicators and parametric criteria.",
            ["WI-101", "QM-001"],
            "medium",
        ),
        (
            "What must happen before a device history record is released?",
            "Per SOP-010, all operations must be complete and records reviewed "
            "before final QA release of the lot.",
            ["SOP-010"],
            "easy",
        ),
    ]


def _trace_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    out = []
    for req in world.requirements:
        if req.req_id in world.trace_gaps:
            continue
        tests = [t for t in world.verification_tests if req.req_id in t.req_ids]
        reports = ", ".join(t.report_id for t in tests)
        titles = "; ".join(t.title for t in tests)
        out.append(
            (
                f"Which verification report(s) provide objective evidence for "
                f'{req.req_id} ("{req.text}")?',
                f"{req.req_id} is verified by {reports} ({titles}) per the "
                "traceability matrix TM-100.",
                ["TM-100", req.req_id],
                "medium",
            )
        )
    return out


def _fmea_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    out = []
    for doc_id, rows in (("DFMEA-100", world.dfmea_rows), ("PFMEA-100", world.pfmea_rows)):
        for r in rows:
            out.append(
                (
                    f"In {doc_id}, what is the recorded action priority for the "
                    f'failure mode "{r.failure_mode}" of {r.item}, and what is '
                    "the detection control?",
                    f"Row {r.row_id} of {doc_id} records action priority "
                    f"{r.ap_recorded} (S={r.severity}, O={r.occurrence}, "
                    f"D={r.detection}); the detection control is "
                    f'"{r.detection_control}".',
                    [doc_id],
                    "medium",
                )
            )
    return out


def _capa_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    out = []
    for capa in world.capas:
        eff = (
            f"the effectiveness check was completed {fmt_date(capa.effectiveness_completed)}"
            if capa.effectiveness_completed
            else f"the effectiveness check (due {fmt_date(capa.effectiveness_due)}) "
            "has not been completed"
        )
        out.append(
            (
                f"What triggered {capa.capa_id}, what root cause was identified, "
                "and is its effectiveness check complete?",
                f"{capa.capa_id} was opened {fmt_date(capa.opened)} from "
                f"{capa.source_type.replace('_', ' ')} {capa.source_id}. Root "
                f"cause: {capa.root_cause} Status: {capa.status}; {eff}.",
                [capa.capa_id],
                "medium",
            )
        )
    return out


def _complaint_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    out = []
    for mdr in world.mdrs:
        complaint = next(c for c in world.complaints if c.complaint_id == mdr.complaint_id)
        out.append(
            (
                f"Which complaint led to {mdr.mdr_id}, and when was the MDR submitted to FDA?",
                f"{mdr.mdr_id} was filed from complaint {complaint.complaint_id} "
                f"({complaint.failure_category.replace('_', ' ')}, received "
                f"{fmt_date(complaint.received)}) and submitted "
                f"{fmt_date(mdr.submitted)} as a {mdr.event_type.replace('_', ' ')} report.",
                [mdr.mdr_id, complaint.complaint_id],
                "medium",
            )
        )
    non_reportable = [c for c in world.complaints if c.mdr_id is None][:6]
    for c in non_reportable:
        out.append(
            (
                f"Was complaint {c.complaint_id} reported to FDA as an MDR?",
                f"No. {c.complaint_id} ({c.failure_category.replace('_', ' ')}, "
                f"received {fmt_date(c.received)}) was evaluated and determined "
                "not reportable; no MDR was filed.",
                [c.complaint_id],
                "easy",
            )
        )
    return out


def _count_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    out = []
    for year in (2024, 2025, 2026):
        n_c = sum(1 for c in world.complaints if c.received.year == year)
        n_n = sum(1 for n in world.ncrs if n.opened.year == year)
        n_k = sum(1 for k in world.capas if k.opened.year == year)
        suffix = " (through 2026-07-01)" if year == 2026 else ""
        out.append(
            (
                f"How many complaints were received in {year}?",
                f"{n_c} complaints were received in {year}{suffix}.",
                [f"corpus:complaints:{year}"],
                "medium",
            )
        )
        out.append(
            (
                f"How many nonconformance reports were opened in {year}?",
                f"{n_n} NCRs were opened in {year}{suffix}.",
                [f"corpus:ncrs:{year}"],
                "medium",
            )
        )
        out.append(
            (
                f"How many CAPAs were opened in {year}?",
                f"{n_k} CAPAs were opened in {year}{suffix}.",
                [f"corpus:capas:{year}"],
                "medium",
            )
        )
    return out


def _training_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    out = []
    for record in world.training[:10]:
        doc = world.doc(record.doc_id)
        out.append(
            (
                f"Is {record.person} trained to the current revision of "
                f"{record.doc_id} ({doc.title})?",
                f"Yes. {record.person} completed training on {record.doc_id} "
                f"Rev {record.rev} on {fmt_date(record.trained)} per TRN-100.",
                ["TRN-100", record.doc_id],
                "medium",
            )
        )
    trained_pairs = {(t.person, t.doc_id) for t in world.training}
    added = 0
    for doc in world.controlled_docs:
        if doc.doc_type not in ("sop", "wi") or added >= 3:
            continue
        for person in world.people:
            if (person.name, doc.doc_id) not in trained_pairs:
                out.append(
                    (
                        f"Is there a training record for {person.name} on {doc.doc_id}?",
                        f"No. TRN-100 shows no training record for {person.name} on {doc.doc_id}.",
                        ["TRN-100", doc.doc_id],
                        "medium",
                    )
                )
                added += 1
                break
    return out


def _supplier_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    out = []
    for component in world.components:
        if not component.supplier_id:
            continue
        supplier = next(s for s in world.suppliers if s.supplier_id == component.supplier_id)
        out.append(
            (
                f"Which supplier provides the {component.name} "
                f"({component.part_number}), and what is their approval status?",
                f"{supplier.name} ({supplier.supplier_id}) supplies the "
                f"{component.name}; approval status is {supplier.approval_status}, "
                f"last audited {fmt_date(supplier.last_audit)} "
                f"({supplier.audit_report_id}).",
                ["ASL-100", supplier.audit_report_id],
                "medium",
            )
        )
    conditional = next(s for s in world.suppliers if s.approval_status == "conditional")
    out.append(
        (
            "Are any suppliers on the approved supplier list conditionally approved, and why?",
            f"Yes. {conditional.name} ({conditional.supplier_id}) is conditionally "
            f"approved: audit {conditional.audit_report_id} found a major "
            "nonconformity in process change notification; the corrective action "
            "plan was accepted pending verification at the next surveillance audit.",
            ["ASL-100", conditional.audit_report_id],
            "hard",
        )
    )
    return out


def _defect_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    by_kind = {d.kind: d for d in world.defects}
    wi101 = world.doc("WI-101")
    questions = (
        (
            "Do all design input requirements have verification evidence in the "
            "traceability matrix? If not, which requirement is missing evidence?",
            by_kind["broken_trace_link"],
        ),
        (
            "In DFMEA-100, is the recorded action priority for the FT-210 "
            'feedthrough failure mode "Hermeticity loss at braze joint" '
            "consistent with its severity, occurrence, and detection ratings?",
            by_kind["ap_mismatch"],
        ),
        (
            "As of 2026-07-01, are any CAPA effectiveness checks overdue?",
            by_kind["overdue_effectiveness_check"],
        ),
        (
            "Were all complaints evaluated against the risk management file as "
            "SOP-006 requires? Identify any exception.",
            by_kind["complaint_without_risk_evaluation"],
        ),
        (
            f"SOP-016 cites WI-101 at a specific revision. Is that reference "
            f"current, given WI-101 is at Rev {wi101.current.rev}?",
            by_kind["stale_sop_reference"],
        ),
        (
            "Which design input requirement covers EO and ECH sterilization "
            "residuals, and has it been verified?",
            by_kind["broken_trace_link"],
        ),
        (
            "Summarize the open compliance gaps an auditor should find in this quality system.",
            None,
        ),
    )
    out = []
    for question, defect in questions:
        if defect is not None:
            out.append((question, defect.ground_truth, list(defect.evidence_ids), "hard"))
        else:
            summary = " ".join(f"({i + 1}) {d.ground_truth}" for i, d in enumerate(world.defects))
            evidence = sorted({e for d in world.defects for e in d.evidence_ids})
            out.append((question, summary, evidence, "hard"))
    return out


def _crosswalk_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    """Auditor questions in the other regulatory dialect: ISO 13485 vocabulary
    for a QSR-phrased quality system (and clause-number lookups both ways).
    These exercise the query-time synonym layer — the corpus never uses these
    phrasings."""
    return [
        (
            "How are advisory notices initiated and who approves them?",
            "Per SOP-019 (Field Action and Recall), advisory notices are handled "
            "as field actions in ISO terms: Regulatory Affairs initiates the "
            "action by convening the field action committee, and the Director of "
            "Quality Assurance approves the classification and the decision to "
            "proceed before any customer notification is issued.",
            ["SOP-019"],
            "hard",
        ),
        (
            "Which procedure covers vigilance reporting of adverse events to "
            "regulatory authorities?",
            "SOP-007 (Medical Device Reporting) covers reporting of adverse "
            "events to FDA under 21 CFR 803 — the vigilance process in ISO terms.",
            ["SOP-007"],
            "hard",
        ),
        (
            "How does top management ensure the quality management system "
            "remains suitable and effective?",
            "SOP-015 (Management Review) requires management with executive "
            "responsibility to review the quality system at defined intervals "
            "for suitability and effectiveness.",
            ["SOP-015"],
            "hard",
        ),
        (
            "What controls exist for the work environment in manufacturing areas?",
            "SOP-018 (Environmental and Contamination Control) defines controls "
            "for the production environment, including cleanliness and "
            "contamination requirements.",
            ["SOP-018"],
            "hard",
        ),
        (
            "Show the procedure for control of nonconforming outputs and the "
            "dispositions it allows.",
            "SOP-005 (Control of Nonconforming Product) governs nonconforming "
            "outputs; dispositions include use-as-is, rework, scrap, and return "
            "to vendor.",
            ["SOP-005"],
            "medium",
        ),
        (
            "How is the fitness of monitoring and measuring equipment maintained?",
            "SOP-011 (Calibration and Preventive Maintenance) controls "
            "monitoring and measuring equipment through calibration and "
            "preventive maintenance.",
            ["SOP-011"],
            "hard",
        ),
        (
            "Which procedure implements ISO 13485 Clause 8.5.2 and Clause 8.5.3?",
            "SOP-004 (Corrective and Preventive Action) implements ISO "
            "13485:2016 Clauses 8.5.2 and 8.5.3.",
            ["SOP-004"],
            "medium",
        ),
        (
            "Which procedure addresses the requirements of 21 CFR 820.90?",
            "SOP-005 (Control of Nonconforming Product) addresses 21 CFR 820.90.",
            ["SOP-005"],
            "medium",
        ),
    ]


def _governance_clinical_questions(world: World) -> list[tuple[str, str, list[str], str]]:
    out = []
    for audit in world.internal_audits:
        capas = ", ".join(audit.capa_ids) if audit.capa_ids else "none"
        out.append(
            (
                f"When was internal audit {audit.audit_id} conducted, who led "
                "it, and did it raise any CAPAs?",
                f"{audit.audit_id} was conducted {fmt_date(audit.audit_date)}, "
                f"led by {audit.lead_auditor}. Result: {audit.result}. CAPAs "
                f"raised: {capas}.",
                [audit.audit_id],
                "medium",
            )
        )
    for review in world.management_reviews:
        out.append(
            (
                f"What period did management review {review.review_id} cover, "
                "and how many CAPAs were opened in that period?",
                f"{review.review_id} met {fmt_date(review.meeting_date)}, "
                f"chaired by {review.chair}, covering "
                f"{fmt_date(review.period_start)} through "
                f"{fmt_date(review.period_end)}; {review.capas_opened} CAPAs "
                "were opened in the period.",
                [review.review_id],
                "medium",
            )
        )
    cip = world.doc("CIP-100")
    cer = world.doc("CER-100")
    out.append(
        (
            "What are the primary endpoints of the HALVERN clinical investigation?",
            f"Per CIP-100 (Rev {cip.current.rev}), the primary effectiveness "
            "endpoint is delivered volume within 15 percent of programmed volume "
            "at the 6-month refill visit; the primary safety endpoint is freedom from "
            "system-related complications at 6 months of at least 92 percent.",
            ["CIP-100"],
            "medium",
        )
    )
    out.append(
        (
            "What does the Clinical Evaluation Report conclude about the "
            "device's benefit-risk profile?",
            f"CER-100 (Rev {cer.current.rev}) concludes the benefit-risk "
            "profile is favorable: residual risks documented in RMR-100 are "
            "acceptable against the therapeutic benefit of targeted drug infusion, and "
            "continued market availability is supported.",
            ["CER-100"],
            "medium",
        )
    )
    out.append(
        (
            "How much post-market experience does the Clinical Evaluation Report cite?",
            f"CER-100 cites {len(world.complaints)} complaints received across "
            f"both models, of which {len(world.mdrs)} met reportability "
            "criteria and were submitted as medical device reports.",
            ["CER-100"],
            "medium",
        )
    )
    for row in world.control_plan_rows[:4]:
        out.append(
            (
                f'Which PFMEA row does the process control for "{row.characteristic}" '
                "address, and what are the control method and reaction plan?",
                f'CTL-100 row {row.row_id} controls "{row.characteristic}" '
                f"({row.specification}) at frequency {row.frequency}, addressing "
                f"PFMEA-100 row {row.pfmea_row}. Control method: "
                f"{row.control_method}. Reaction plan: {row.reaction_plan}.",
                ["CTL-100"],
                "medium",
            )
        )
    return out


# Record ids a question can name; one per family so neighbours are found by order.
_RECORD_ID_RE = re.compile(
    r"\b(?:CAPA-\d{4}-\d{3}|C-\d{4}-\d{4}|NCR-\d{4}-\d{3,}|MDR-\d{4}|AUD-\d{4}-\d{2}|MRM-\d{4}-\d{2})\b"
)


def _record_families(world: World) -> list[list[str]]:
    return [
        sorted(c.capa_id for c in world.capas),
        sorted(c.complaint_id for c in world.complaints),
        sorted(n.ncr_id for n in world.ncrs),
        sorted(m.mdr_id for m in world.mdrs),
        sorted(a.audit_id for a in world.internal_audits),
        sorted(r.review_id for r in world.management_reviews),
    ]


def _neighbour_exclusions(
    question: str, evidence: list[str], families: list[list[str]]
) -> list[str]:
    """The records either side of the one record a question names. Exact-record
    scope must keep them out of the results."""
    named = set(_RECORD_ID_RE.findall(question))
    if len(named) != 1:
        return []
    (record_id,) = named
    for family in families:
        if record_id in family:
            i = family.index(record_id)
            neighbours = family[max(i - 1, 0) : i] + family[i + 1 : i + 2]
            return [n for n in neighbours if n not in evidence]
    return []


def _revision_expectations(world: World, doc_id: str) -> tuple[dict[str, str], list[str]]:
    """Pin the current revision; exclude the prior one where it is rendered as
    an archived file (SOPs and WIs with history)."""
    doc = world.doc(doc_id)
    exclude = []
    if doc.doc_type in ("sop", "wi") and len(doc.revisions) > 1:
        exclude.append(f"{doc_id}@{doc.revisions[-2].rev}")
    return {doc_id: doc.current.rev}, exclude


def _expectations(
    world: World, pattern: str, question: str, doc_ids: list[str], families: list[list[str]]
) -> tuple[list[str], dict[str, str]]:
    if pattern == "revision_approval" and len(doc_ids) == 1:
        revisions, exclude = _revision_expectations(world, doc_ids[0])
        return exclude, revisions
    return _neighbour_exclusions(question, doc_ids, families), {}


def build_qa_set(world: World) -> QaSet:
    generators: tuple[tuple[Pattern, list[tuple[str, str, list[str], str]]], ...] = (
        ("revision_approval", _revision_questions(world)),
        ("procedure_content", _content_questions(world)),
        ("trace_walk", _trace_questions(world)),
        ("fmea_risk", _fmea_questions(world)),
        ("capa_thread", _capa_questions(world)),
        ("complaint_mdr", _complaint_questions(world)),
        ("counts_aggregates", _count_questions(world)),
        ("training", _training_questions(world)),
        ("supplier", _supplier_questions(world)),
        ("defect_discovery", _defect_questions(world)),
        ("regulatory_crosswalk", _crosswalk_questions(world)),
        ("governance_clinical", _governance_clinical_questions(world)),
    )
    items: list[QaItem] = []
    counter = 1
    families = _record_families(world)
    for pattern, rows in generators:
        for i, (question, answer, evidence, difficulty) in enumerate(rows):
            doc_ids, source_ids = _split_evidence(evidence)
            must_exclude, evidence_revisions = _expectations(
                world, pattern, question, doc_ids, families
            )
            items.append(
                QaItem(
                    id=f"QA-{counter:04d}",
                    question=question,
                    answer=answer,
                    pattern=pattern,
                    evidence_doc_ids=doc_ids,
                    answer_source_ids=source_ids,
                    expected_routes=list(_PATTERN_ROUTES[pattern]),
                    must_exclude=must_exclude,
                    evidence_revisions=evidence_revisions,
                    smoke=i < _SMOKE_QUOTA[pattern],
                    difficulty=difficulty,  # type: ignore[arg-type]
                )
            )
            counter += 1
    return QaSet(
        schema_version=QA_SCHEMA_VERSION,
        seed=world.seed,
        world_today=ids.WORLD_TODAY.isoformat(),
        company=world.company,
        items=items,
    )
