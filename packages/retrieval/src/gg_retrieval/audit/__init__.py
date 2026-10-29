"""Audit-readiness workflows: deterministic gates over the derived
projections, grouped into audit-prep collections, with an optional
advisory LLM note layered on top."""

from gg_retrieval.audit.advisory import advisory_note
from gg_retrieval.audit.checks import (
    AUDIT_CHECKS,
    AUDIT_COLLECTIONS,
    CHECKS_BY_ID,
    COLLECTIONS_BY_ID,
    AuditCheck,
    AuditCollection,
)
from gg_retrieval.audit.report import AuditReport, AuditReportRunner, CheckResult

__all__ = [
    "AUDIT_CHECKS",
    "AUDIT_COLLECTIONS",
    "CHECKS_BY_ID",
    "COLLECTIONS_BY_ID",
    "AuditCheck",
    "AuditCollection",
    "AuditReport",
    "AuditReportRunner",
    "CheckResult",
    "advisory_note",
]
