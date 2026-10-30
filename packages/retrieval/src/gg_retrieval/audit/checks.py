"""The audit-readiness check catalogue.

Every check is a deterministic gate over the derived projections — a saved
warehouse query or a whitelisted graph traversal — whose finding condition
is simply "returned rows". The gap checks encode the seeded-defect patterns
from the synthetic corpus, so a clean corpus passes every gate and each
seeded defect trips exactly the gate built for its pattern.
"""

from dataclasses import dataclass
from typing import Literal

CheckKind = Literal["gap", "reconciliation", "currency"]
CheckSource = Literal["warehouse", "graph"]


@dataclass(frozen=True)
class AuditCheck:
    check_id: str
    title: str
    description: str
    kind: CheckKind
    source: CheckSource
    ref: str  # saved-query name (warehouse) or parameterless GraphWalker method
    defect_kind: str | None = None  # seeded-defect pattern this gate encodes


AUDIT_CHECKS: tuple[AuditCheck, ...] = (
    AuditCheck(
        check_id="unverified_requirements",
        title="Requirements without verification evidence",
        description="Trace-matrix rows with no verification protocol or report.",
        kind="gap",
        source="warehouse",
        ref="unverified_requirements",
        defect_kind="broken_trace_link",
    ),
    AuditCheck(
        check_id="fmea_ap_mismatches",
        title="FMEA action-priority mismatches",
        description="FMEA rows whose recorded AP disagrees with the configured AP table.",
        kind="gap",
        source="warehouse",
        ref="fmea_ap_mismatches",
        defect_kind="ap_mismatch",
    ),
    AuditCheck(
        check_id="overdue_capa_effectiveness",
        title="Overdue CAPA effectiveness checks",
        description="CAPAs whose effectiveness check due date passed without completion.",
        kind="gap",
        source="warehouse",
        ref="overdue_capa_effectiveness",
        defect_kind="overdue_effectiveness_check",
    ),
    AuditCheck(
        check_id="complaints_without_risk_evaluation",
        title="Complaints without a risk evaluation",
        description="Complaint files never evaluated against the risk management file.",
        kind="gap",
        source="warehouse",
        ref="complaints_without_risk_evaluation",
        defect_kind="complaint_without_risk_evaluation",
    ),
    AuditCheck(
        check_id="stale_document_references",
        title="Documents citing superseded revisions",
        description="Controlled documents citing another document at a superseded revision.",
        kind="gap",
        source="graph",
        ref="stale_references",
        defect_kind="stale_sop_reference",
    ),
    AuditCheck(
        check_id="complaint_mdr_reconciliation",
        title="Complaint log vs MDR register",
        description="Cross-references complaints and filed MDRs in both directions.",
        kind="reconciliation",
        source="warehouse",
        ref="complaint_mdr_reconciliation",
    ),
    AuditCheck(
        check_id="training_revision_reconciliation",
        title="Training log vs document revisions",
        description="Training records taken against a revision that has been superseded.",
        kind="reconciliation",
        source="graph",
        ref="stale_training",
    ),
    AuditCheck(
        check_id="aging_open_capas",
        title="Aging open CAPAs",
        description="CAPAs still open past 90 days.",
        kind="currency",
        source="warehouse",
        ref="aging_open_capas",
    ),
    AuditCheck(
        check_id="overdue_supplier_audits",
        title="Overdue supplier audits",
        description="Suppliers never audited or with no audit in the past year.",
        kind="currency",
        source="warehouse",
        ref="overdue_supplier_audits",
    ),
)

CHECKS_BY_ID: dict[str, AuditCheck] = {check.check_id: check for check in AUDIT_CHECKS}


@dataclass(frozen=True)
class AuditCollection:
    collection_id: str
    title: str
    description: str
    check_ids: tuple[str, ...]


AUDIT_COLLECTIONS: tuple[AuditCollection, ...] = (
    AuditCollection(
        collection_id="design_controls",
        title="Design controls",
        description="Trace completeness and risk-analysis integrity.",
        check_ids=("unverified_requirements", "fmea_ap_mismatches"),
    ),
    AuditCollection(
        collection_id="capa_and_complaints",
        title="CAPA and complaints",
        description="CAPA discipline, complaint handling, and MDR reconciliation.",
        check_ids=(
            "overdue_capa_effectiveness",
            "complaints_without_risk_evaluation",
            "complaint_mdr_reconciliation",
            "aging_open_capas",
        ),
    ),
    AuditCollection(
        collection_id="document_control_and_training",
        title="Document control and training",
        description="Reference currency and training against current revisions.",
        check_ids=("stale_document_references", "training_revision_reconciliation"),
    ),
    AuditCollection(
        collection_id="supplier_controls",
        title="Supplier controls",
        description="Supplier audit currency.",
        check_ids=("overdue_supplier_audits",),
    ),
)

COLLECTIONS_BY_ID: dict[str, AuditCollection] = {
    collection.collection_id: collection for collection in AUDIT_COLLECTIONS
}
