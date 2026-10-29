"""Record warehouse tool: saved queries first, guarded ad-hoc SQL second.

Queries only the curated registers.v_* views (never base tables), executed
under three stacked guards: sqlguard validation, a read-only transaction,
and SET LOCAL ROLE sql_tool_ro whose grants are SELECT-only. The saved
queries cover the standing audit questions so ad-hoc text-to-SQL is the
exception, not the norm.
"""

from dataclasses import dataclass
from typing import Any

from gg_common import acl
from gg_common.settings import AppSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gg_retrieval.tools.models import ToolResult, plain_row
from gg_retrieval.tools.sqlguard import SqlGuardError, validate_select

# The curated SQL surface. Columns mirror migration 0004; an integration test
# asserts this map matches the live views so drift cannot go unnoticed.
REGISTER_VIEWS: dict[str, tuple[str, ...]] = {
    "registers.v_ncr_register": (
        "ncr_id",
        "opened",
        "part_number",
        "part_name",
        "supplier_id",
        "description",
        "disposition",
        "capa_id",
        "status",
        "closed",
        "is_open",
        "age_days",
    ),
    "registers.v_capa_register": (
        "capa_id",
        "opened",
        "source_type",
        "source_id",
        "owner",
        "status",
        "description",
        "root_cause",
        "corrective_action",
        "effectiveness_due",
        "effectiveness_completed",
        "closed",
        "is_open",
        "age_days",
        "effectiveness_overdue",
    ),
    "registers.v_complaint_register": (
        "complaint_id",
        "received",
        "device_model",
        "lot",
        "failure_category",
        "description",
        "investigation",
        "risk_evaluated",
        "risk_reference",
        "mdr_id",
        "status",
        "closed",
        "is_open",
        "age_days",
    ),
    "registers.v_mdr_register": (
        "mdr_id",
        "complaint_id",
        "submitted",
        "event_type",
        "device_model",
        "lot",
        "description",
    ),
    "registers.v_supplier_register": (
        "supplier_id",
        "name",
        "commodity",
        "approval_status",
        "last_audit",
        "audit_report_id",
        "days_since_audit",
    ),
    "registers.v_supplier_audit_register": (
        "report_id",
        "supplier_id",
        "audit_date",
        "audit_type",
        "result",
        "findings",
    ),
    "registers.v_fmea_register": (
        "doc_key",
        "row_id",
        "item",
        "function",
        "failure_mode",
        "effect",
        "cause",
        "prevention_control",
        "detection_control",
        "severity",
        "occurrence",
        "detection",
        "ap_recorded",
        "ap_computed",
        "ap_mismatch",
        "risk_file_refs",
    ),
    "registers.v_trace_register": (
        "req_id",
        "category",
        "requirement_text",
        "design_outputs",
        "protocols",
        "reports",
        "results",
        "completed",
        "has_verification",
    ),
    "registers.v_training_register": (
        "person",
        "role",
        "doc_key",
        "revision",
        "trained_on",
    ),
}

ALLOWED_RELATIONS = frozenset(REGISTER_VIEWS)

# Views over restricted record families (complaint and MDR narratives). A
# role without restricted access queries against a whitelist with these
# removed, so the guard rejects the SQL before it reaches the database; row
# level security on the underlying tables backstops the same rule there.
RESTRICTED_RELATIONS = frozenset({"registers.v_complaint_register", "registers.v_mdr_register"})


def relations_for_role(role: str) -> frozenset[str]:
    if acl.can_read_restricted(role):
        return ALLOWED_RELATIONS
    return ALLOWED_RELATIONS - RESTRICTED_RELATIONS


@dataclass(frozen=True)
class SavedQuery:
    title: str
    description: str
    sql: str
    source: str
    params: tuple[str, ...] = ()


SAVED_QUERIES: dict[str, SavedQuery] = {
    "open_ncrs": SavedQuery(
        title="Open NCRs",
        description="Nonconformance reports not yet closed, oldest first.",
        sql=(
            "SELECT ncr_id, opened, part_number, part_name, supplier_id, disposition,"
            " capa_id, status, age_days FROM registers.v_ncr_register"
            " WHERE is_open ORDER BY opened"
        ),
        source="registers.v_ncr_register",
    ),
    "open_capas": SavedQuery(
        title="Open CAPAs",
        description="CAPAs not yet closed, oldest first.",
        sql=(
            "SELECT capa_id, opened, source_type, source_id, owner, status,"
            " effectiveness_due, age_days FROM registers.v_capa_register"
            " WHERE is_open ORDER BY opened"
        ),
        source="registers.v_capa_register",
    ),
    "overdue_capa_effectiveness": SavedQuery(
        title="CAPAs with overdue effectiveness checks",
        description="Effectiveness check due date passed with no completion recorded.",
        sql=(
            "SELECT capa_id, opened, owner, status, effectiveness_due,"
            " effectiveness_completed, closed FROM registers.v_capa_register"
            " WHERE effectiveness_overdue ORDER BY effectiveness_due"
        ),
        source="registers.v_capa_register",
    ),
    "complaints_without_risk_evaluation": SavedQuery(
        title="Complaints without a documented risk evaluation",
        description="Complaint files whose risk evaluation field is empty.",
        sql=(
            "SELECT complaint_id, received, device_model, failure_category, mdr_id, status"
            " FROM registers.v_complaint_register WHERE NOT risk_evaluated ORDER BY received"
        ),
        source="registers.v_complaint_register",
    ),
    "mdr_register": SavedQuery(
        title="MDR submissions",
        description="All medical device reports with their source complaints.",
        sql=(
            "SELECT mdr_id, complaint_id, submitted, event_type, device_model, lot"
            " FROM registers.v_mdr_register ORDER BY submitted"
        ),
        source="registers.v_mdr_register",
    ),
    "unverified_requirements": SavedQuery(
        title="Requirements without verification",
        description="Trace matrix rows with no verification report recorded.",
        sql=(
            "SELECT req_id, category, requirement_text, design_outputs, protocols"
            " FROM registers.v_trace_register WHERE NOT has_verification ORDER BY req_id"
        ),
        source="registers.v_trace_register",
    ),
    "fmea_ap_mismatches": SavedQuery(
        title="FMEA rows where recorded AP disagrees with computed AP",
        description="Action priority recorded in the sheet differs from the AIAG-VDA table.",
        sql=(
            "SELECT doc_key, row_id, item, failure_mode, severity, occurrence, detection,"
            " ap_recorded, ap_computed FROM registers.v_fmea_register"
            " WHERE ap_mismatch ORDER BY doc_key, row_id"
        ),
        source="registers.v_fmea_register",
    ),
    "supplier_audit_aging": SavedQuery(
        title="Suppliers by time since last audit",
        description="Approved supplier list ordered by audit age, stalest first.",
        sql=(
            "SELECT supplier_id, name, commodity, approval_status, last_audit,"
            " audit_report_id, days_since_audit FROM registers.v_supplier_register"
            " ORDER BY days_since_audit DESC"
        ),
        source="registers.v_supplier_register",
    ),
    "training_for_document": SavedQuery(
        title="Training status for one document",
        description="Who trained on which revision of the given document.",
        sql=(
            "SELECT person, role, revision, trained_on FROM registers.v_training_register"
            " WHERE doc_key = :doc_key ORDER BY person"
        ),
        source="registers.v_training_register",
        params=("doc_key",),
    ),
    "complaint_mdr_reconciliation": SavedQuery(
        title="Complaint log vs MDR register reconciliation",
        description=(
            "Cross-references the two logs in both directions: complaints citing"
            " an MDR that was never filed, MDRs citing a complaint that does not"
            " exist, and filed MDRs the complaint log does not link back to."
        ),
        sql=(
            "SELECT c.complaint_id AS record_id, c.mdr_id AS related_id,"
            " 'complaint cites an MDR missing from the MDR register' AS discrepancy"
            " FROM registers.v_complaint_register c"
            " LEFT JOIN registers.v_mdr_register m ON m.mdr_id = c.mdr_id"
            " WHERE c.mdr_id IS NOT NULL AND m.mdr_id IS NULL"
            " UNION ALL"
            " SELECT m.mdr_id, m.complaint_id,"
            " 'MDR cites a complaint missing from the complaint log'"
            " FROM registers.v_mdr_register m"
            " LEFT JOIN registers.v_complaint_register c ON c.complaint_id = m.complaint_id"
            " WHERE m.complaint_id IS NOT NULL AND c.complaint_id IS NULL"
            " UNION ALL"
            " SELECT m.mdr_id, m.complaint_id,"
            " 'MDR filed but the complaint log does not link back to it'"
            " FROM registers.v_mdr_register m"
            " JOIN registers.v_complaint_register c ON c.complaint_id = m.complaint_id"
            " WHERE (c.mdr_id IS NULL OR c.mdr_id <> m.mdr_id)"
        ),
        source="registers.v_complaint_register vs registers.v_mdr_register",
    ),
    "aging_open_capas": SavedQuery(
        title="Open CAPAs older than 90 days",
        description="CAPAs still open past 90 days, oldest first.",
        sql=(
            "SELECT capa_id, opened, source_type, owner, status, effectiveness_due,"
            " age_days FROM registers.v_capa_register"
            " WHERE is_open AND age_days > 90 ORDER BY age_days DESC"
        ),
        source="registers.v_capa_register",
    ),
    "overdue_supplier_audits": SavedQuery(
        title="Suppliers overdue for audit",
        description="Suppliers never audited or with no audit in the past year.",
        sql=(
            "SELECT supplier_id, name, commodity, approval_status, last_audit,"
            " days_since_audit FROM registers.v_supplier_register"
            " WHERE last_audit IS NULL OR days_since_audit > 365"
            " ORDER BY days_since_audit DESC"
        ),
        source="registers.v_supplier_register",
    ),
    "register_counts": SavedQuery(
        title="Record counts per register",
        description="How many records each register currently holds.",
        sql=(
            "SELECT 'ncr' AS register, count(*) AS records FROM registers.v_ncr_register"
            " UNION ALL SELECT 'capa', count(*) FROM registers.v_capa_register"
            " UNION ALL SELECT 'complaint', count(*) FROM registers.v_complaint_register"
            " UNION ALL SELECT 'mdr', count(*) FROM registers.v_mdr_register"
            " UNION ALL SELECT 'supplier', count(*) FROM registers.v_supplier_register"
            " UNION ALL SELECT 'supplier_audit', count(*)"
            " FROM registers.v_supplier_audit_register"
            " UNION ALL SELECT 'fmea_row', count(*) FROM registers.v_fmea_register"
            " UNION ALL SELECT 'requirement_trace', count(*) FROM registers.v_trace_register"
            " UNION ALL SELECT 'training', count(*) FROM registers.v_training_register"
        ),
        source="registers.v_* views",
    ),
}


class WarehouseTool:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: AppSettings,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings

    async def run_saved(
        self, name: str, params: dict[str, Any] | None = None, *, role: str = "admin"
    ) -> ToolResult:
        query = SAVED_QUERIES.get(name)
        if query is None:
            available = ", ".join(sorted(SAVED_QUERIES))
            raise LookupError(f"unknown saved query: {name} (available: {available})")
        provided = frozenset(params or {})
        if provided != frozenset(query.params):
            raise SqlGuardError(
                f"saved query '{name}' requires params {sorted(query.params)},"
                f" got {sorted(provided)}"
            )
        return await self._execute(
            query.sql, params or {}, title=query.title, source=query.source, role=role
        )

    async def run_sql(
        self, sql: str, *, title: str = "Ad-hoc register query", role: str = "admin"
    ) -> ToolResult:
        return await self._execute(
            sql, {}, title=title, source="registers warehouse (ad-hoc SQL)", role=role
        )

    async def _execute(
        self, sql: str, params: dict[str, Any], *, title: str, source: str, role: str
    ) -> ToolResult:
        validated = validate_select(sql, allowed_relations=relations_for_role(role))
        limit = self.settings.tools.sql_row_limit
        timeout_ms = self.settings.tools.sql_timeout_ms
        wrapped = f"SELECT * FROM ({validated}) AS gg_guarded LIMIT {limit + 1}"

        async with self.session_factory() as session:
            try:
                # SET accepts no bind parameters; the interpolated values are
                # ints from validated settings, never model-authored strings.
                await session.execute(text("SET TRANSACTION READ ONLY"))
                await session.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
                # Row level security on restricted registers keys off this
                # transaction-local flag; unset it reads as off, so a path
                # that forgets to declare a role sees no restricted rows.
                restricted_ok = "on" if acl.can_read_restricted(role) else "off"
                await session.execute(
                    text("SELECT set_config('gg.read_restricted', :flag, true)"),
                    {"flag": restricted_ok},
                )
                await session.execute(text("SET LOCAL ROLE sql_tool_ro"))
                result = await session.execute(text(wrapped), params)
                columns = tuple(result.keys())
                fetched = [plain_row(dict(row)) for row in result.mappings().all()]
            finally:
                # Read-only work: always roll back so the role and transaction
                # flags never leak into the pooled connection.
                await session.rollback()

        truncated = len(fetched) > limit
        rows = tuple(fetched[:limit])
        return ToolResult(
            tool="warehouse",
            title=title,
            source=source,
            query=validated,
            columns=columns,
            rows=rows,
            truncated=truncated,
        )
