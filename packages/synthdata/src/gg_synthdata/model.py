"""Entity model for the synthetic Halvern Medical world.

Everything is a frozen dataclass built once by world.build_world(); renderers
and the QA generator consume the same objects, so documents and ground truth
can never drift apart.
"""

from dataclasses import dataclass, field
from datetime import date

from gg_common.actionpriority import compute_action_priority


@dataclass(frozen=True)
class Person:
    name: str
    role: str
    initials: str
    department: str


@dataclass(frozen=True)
class Component:
    part_number: str
    name: str
    function: str
    parent: str | None
    supplier_id: str | None = None


@dataclass(frozen=True)
class Revision:
    rev: str
    rev_date: date
    description: str
    author: str
    approver: str


@dataclass(frozen=True)
class ControlledDoc:
    doc_id: str
    title: str
    doc_type: str  # quality_manual | sop | wi | design_plan | risk_plan | ...
    department: str
    revisions: tuple[Revision, ...]
    references: tuple[str, ...] = ()
    regulation_refs: tuple[str, ...] = ()

    @property
    def current(self) -> Revision:
        return self.revisions[-1]


@dataclass(frozen=True)
class Requirement:
    req_id: str
    text: str
    category: str
    source: str


@dataclass(frozen=True)
class DesignOutput:
    do_id: str
    title: str
    kind: str  # drawing | specification | firmware
    req_ids: tuple[str, ...]


@dataclass(frozen=True)
class VerificationTest:
    protocol_id: str
    report_id: str
    title: str
    req_ids: tuple[str, ...]
    result: str  # pass | fail | pass_with_deviation
    completed: date | None


@dataclass(frozen=True)
class FmeaRow:
    row_id: int
    item: str
    function: str
    failure_mode: str
    effect: str
    cause: str
    severity: int
    occurrence: int
    detection: int
    ap_recorded: str  # H | M | L as written in the sheet
    ap_correct: str  # per the AIAG-VDA table (may differ when a defect is seeded)
    prevention_control: str
    detection_control: str
    mitigation_refs: tuple[str, ...] = ()
    realizes_dfmea_row: int | None = None  # PFMEA rows only: DFMEA-100 row realized here


@dataclass(frozen=True)
class Ncr:
    ncr_id: str
    opened: date
    part_number: str
    description: str
    disposition: str  # use_as_is | rework | scrap | return_to_vendor
    status: str  # open | closed
    closed: date | None
    capa_id: str | None
    supplier_id: str | None


@dataclass(frozen=True)
class Capa:
    capa_id: str
    opened: date
    source_type: str  # ncr | complaint | internal_audit
    source_id: str
    description: str
    root_cause: str
    corrective_action: str
    status: str  # open | closed
    closed: date | None
    effectiveness_due: date
    effectiveness_completed: date | None
    owner: str


@dataclass(frozen=True)
class Complaint:
    complaint_id: str
    received: date
    model: str
    lot: str
    description: str
    failure_category: str
    investigation: str
    risk_evaluated: bool
    risk_reference: str | None  # e.g. "RA-100 §5.3" when evaluated
    mdr_id: str | None
    status: str  # open | closed
    closed: date | None


@dataclass(frozen=True)
class Mdr:
    mdr_id: str
    complaint_id: str
    submitted: date
    event_type: str  # malfunction | serious_injury | death


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str
    commodity: str
    approval_status: str  # approved | conditional
    audit_report_id: str
    last_audit: date


@dataclass(frozen=True)
class TravelerStep:
    seq: int
    operation: str
    sop_ref: str
    operator_initials: str
    completed: date
    result: str  # accept | reject


@dataclass(frozen=True)
class Traveler:
    lot: str
    model: str
    quantity: int
    started: date
    steps: tuple[TravelerStep, ...]
    scanned: bool  # rendered as image-only PDF when True


@dataclass(frozen=True)
class TrainingRecord:
    person: str
    doc_id: str
    rev: str
    trained: date


@dataclass(frozen=True)
class InternalAudit:
    audit_id: str
    audit_date: date
    lead_auditor: str
    areas: tuple[str, ...]
    scope_docs: tuple[str, ...]
    findings: tuple[str, ...]
    capa_ids: tuple[str, ...]  # CAPAs whose source cites this audit
    result: str  # Conforming | Conforming with findings


@dataclass(frozen=True)
class ManagementReview:
    review_id: str
    meeting_date: date
    period_start: date
    period_end: date
    chair: str
    attendees: tuple[str, ...]
    capas_opened: int
    capas_closed: int
    ncrs_opened: int
    complaints_received: int
    mdrs_submitted: int
    audit_ids: tuple[str, ...]  # internal audits conducted in the period
    decisions: tuple[str, ...]


@dataclass(frozen=True)
class ControlPlanRow:
    row_id: int
    process_step: str
    pfmea_row: int  # row in PFMEA-100 this control addresses
    characteristic: str
    specification: str
    control_method: str
    frequency: str
    reference: str  # governing WI or SOP
    reaction_plan: str


@dataclass(frozen=True)
class SeededDefect:
    defect_id: str
    kind: str
    description: str
    evidence_ids: tuple[str, ...]
    ground_truth: str


@dataclass(frozen=True)
class World:
    seed: int
    company: str
    people: tuple[Person, ...]
    components: tuple[Component, ...]
    controlled_docs: tuple[ControlledDoc, ...]
    requirements: tuple[Requirement, ...]
    design_outputs: tuple[DesignOutput, ...]
    verification_tests: tuple[VerificationTest, ...]
    trace_gaps: tuple[str, ...]  # req_ids intentionally missing verification
    dfmea_rows: tuple[FmeaRow, ...]
    pfmea_rows: tuple[FmeaRow, ...]
    ncrs: tuple[Ncr, ...]
    capas: tuple[Capa, ...]
    complaints: tuple[Complaint, ...]
    mdrs: tuple[Mdr, ...]
    suppliers: tuple[Supplier, ...]
    travelers: tuple[Traveler, ...]
    training: tuple[TrainingRecord, ...]
    internal_audits: tuple[InternalAudit, ...]
    management_reviews: tuple[ManagementReview, ...]
    clinical_docs: tuple[ControlledDoc, ...]
    control_plan_doc: ControlledDoc
    control_plan_rows: tuple[ControlPlanRow, ...]
    defects: tuple[SeededDefect, ...]
    doc_index: dict[str, ControlledDoc] = field(default_factory=dict)

    def doc(self, doc_id: str) -> ControlledDoc:
        return self.doc_index[doc_id]


def ap_from_sod(severity: int, occurrence: int, detection: int) -> str:
    """Action priority per the full AIAG-VDA 1st edition table.

    Delegates to the canonical implementation in gg_common so generated
    sheets and the warehouse AP recompute can never disagree on the table.
    """
    return compute_action_priority(severity, occurrence, detection)
