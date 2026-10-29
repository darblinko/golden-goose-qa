"""Register warehouse loading.

The registers schema is a rebuildable projection of the parsed corpus:
derive deletes every managed table and re-inserts inside one transaction, so
the warehouse is always exactly what the current extraction produced — no
stale rows, fully idempotent. Column lists are the single contract between
extractors and the 0004 migration; a mismatched row fails loudly.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from gg_ingestion.extract.model import DocExtraction, RegisterRow

REGISTER_COLUMNS: dict[str, tuple[str, ...]] = {
    "ncr": (
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
        "source_doc_key",
    ),
    "capa": (
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
        "source_doc_key",
    ),
    "complaint": (
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
        "source_doc_key",
    ),
    "mdr": (
        "mdr_id",
        "complaint_id",
        "submitted",
        "event_type",
        "device_model",
        "lot",
        "description",
        "source_doc_key",
    ),
    "supplier": (
        "supplier_id",
        "name",
        "commodity",
        "approval_status",
        "last_audit",
        "audit_report_id",
        "source_doc_key",
    ),
    "supplier_audit": (
        "report_id",
        "supplier_id",
        "audit_date",
        "audit_type",
        "result",
        "findings",
        "source_doc_key",
    ),
    "fmea_row": (
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
    "requirement_trace": (
        "req_id",
        "category",
        "requirement_text",
        "design_outputs",
        "protocols",
        "reports",
        "results",
        "completed",
        "has_verification",
        "source_doc_key",
    ),
    "training": (
        "person",
        "role",
        "doc_key",
        "revision",
        "trained_on",
        "source_doc_key",
    ),
}


class RegisterContractError(ValueError):
    pass


def validate_row(row: RegisterRow) -> None:
    columns = REGISTER_COLUMNS.get(row.table)
    if columns is None:
        raise RegisterContractError(f"unknown register table: {row.table}")
    if set(row.values) != set(columns):
        missing = set(columns) - set(row.values)
        extra = set(row.values) - set(columns)
        raise RegisterContractError(
            f"registers.{row.table} row mismatch: missing={sorted(missing)} extra={sorted(extra)}"
        )


def _insert_statement(table: str) -> str:
    columns = REGISTER_COLUMNS[table]
    column_list = ", ".join(f'"{c}"' for c in columns)
    param_list = ", ".join(f":{c}" for c in columns)
    return f"INSERT INTO registers.{table} ({column_list}) VALUES ({param_list})"


async def load_registers(session: AsyncSession, extractions: list[DocExtraction]) -> int:
    """Rebuild every managed register table from the extractions. Caller commits."""
    for table in REGISTER_COLUMNS:
        await session.execute(text(f"DELETE FROM registers.{table}"))
    inserted = 0
    for extraction in extractions:
        for row in extraction.register_rows:
            validate_row(row)
            await session.execute(text(_insert_statement(row.table)), row.values)
            inserted += 1
    return inserted
