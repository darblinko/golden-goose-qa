"""Register warehouse: structured QMS records derived from parsed documents.

registers.* tables are a rebuildable projection loaded by `gg-ingest derive`
(delete-then-insert in one transaction). The v_* views are the curated
surface the SQL tool queries — they add audit-relevant computed columns
(is_open, age_days, effectiveness_overdue, ap_mismatch) so the agent never
needs date arithmetic in generated SQL.

0001 default privileges already grant SELECT on new registers tables to
sql_tool_ro; the explicit grants here cover gg_app writes and are
belt-and-braces for the read role.

Revision ID: 0004_registers
Revises: 0003_chat_threads
"""

from alembic import op

revision = "0004_registers"
down_revision = "0003_chat_threads"
branch_labels = None
depends_on = None

_TABLES = (
    """
    CREATE TABLE registers.ncr (
        ncr_id text PRIMARY KEY,
        opened date,
        part_number text NOT NULL DEFAULT '',
        part_name text NOT NULL DEFAULT '',
        supplier_id text,
        description text NOT NULL DEFAULT '',
        disposition text NOT NULL DEFAULT '',
        capa_id text,
        status text NOT NULL DEFAULT '',
        closed date,
        source_doc_key text NOT NULL,
        extracted_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE registers.capa (
        capa_id text PRIMARY KEY,
        opened date,
        source_type text NOT NULL DEFAULT '',
        source_id text,
        owner text NOT NULL DEFAULT '',
        status text NOT NULL DEFAULT '',
        description text NOT NULL DEFAULT '',
        root_cause text NOT NULL DEFAULT '',
        corrective_action text NOT NULL DEFAULT '',
        effectiveness_due date,
        effectiveness_completed date,
        closed date,
        source_doc_key text NOT NULL,
        extracted_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE registers.complaint (
        complaint_id text PRIMARY KEY,
        received date,
        device_model text NOT NULL DEFAULT '',
        lot text NOT NULL DEFAULT '',
        failure_category text NOT NULL DEFAULT '',
        description text NOT NULL DEFAULT '',
        investigation text NOT NULL DEFAULT '',
        risk_evaluated boolean NOT NULL DEFAULT false,
        risk_reference text,
        mdr_id text,
        status text NOT NULL DEFAULT '',
        closed date,
        source_doc_key text NOT NULL,
        extracted_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE registers.mdr (
        mdr_id text PRIMARY KEY,
        complaint_id text,
        submitted date,
        event_type text NOT NULL DEFAULT '',
        device_model text NOT NULL DEFAULT '',
        lot text NOT NULL DEFAULT '',
        description text NOT NULL DEFAULT '',
        source_doc_key text NOT NULL,
        extracted_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE registers.supplier (
        supplier_id text PRIMARY KEY,
        name text NOT NULL DEFAULT '',
        commodity text NOT NULL DEFAULT '',
        approval_status text NOT NULL DEFAULT '',
        last_audit date,
        audit_report_id text,
        source_doc_key text NOT NULL,
        extracted_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE registers.supplier_audit (
        report_id text PRIMARY KEY,
        supplier_id text,
        audit_date date,
        audit_type text NOT NULL DEFAULT '',
        result text NOT NULL DEFAULT '',
        findings text NOT NULL DEFAULT '',
        source_doc_key text NOT NULL,
        extracted_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE registers.fmea_row (
        doc_key text NOT NULL,
        row_id integer NOT NULL,
        item text NOT NULL DEFAULT '',
        "function" text NOT NULL DEFAULT '',
        failure_mode text NOT NULL DEFAULT '',
        effect text NOT NULL DEFAULT '',
        cause text NOT NULL DEFAULT '',
        prevention_control text NOT NULL DEFAULT '',
        detection_control text NOT NULL DEFAULT '',
        severity integer NOT NULL,
        occurrence integer NOT NULL,
        detection integer NOT NULL,
        ap_recorded text NOT NULL DEFAULT '',
        ap_computed text NOT NULL DEFAULT '',
        ap_mismatch boolean NOT NULL DEFAULT false,
        risk_file_refs text NOT NULL DEFAULT '',
        extracted_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (doc_key, row_id)
    )
    """,
    """
    CREATE TABLE registers.requirement_trace (
        req_id text PRIMARY KEY,
        category text NOT NULL DEFAULT '',
        requirement_text text NOT NULL DEFAULT '',
        design_outputs text NOT NULL DEFAULT '',
        protocols text NOT NULL DEFAULT '',
        reports text NOT NULL DEFAULT '',
        results text NOT NULL DEFAULT '',
        completed text NOT NULL DEFAULT '',
        has_verification boolean NOT NULL DEFAULT false,
        source_doc_key text NOT NULL,
        extracted_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE registers.training (
        person text NOT NULL,
        role text NOT NULL DEFAULT '',
        doc_key text NOT NULL,
        revision text NOT NULL DEFAULT '',
        trained_on date,
        source_doc_key text NOT NULL,
        extracted_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (person, doc_key)
    )
    """,
)

_VIEWS = (
    """
    CREATE VIEW registers.v_ncr_register AS
    SELECT ncr_id, opened, part_number, part_name, supplier_id, description,
           disposition, capa_id, status, closed,
           closed IS NULL AS is_open,
           COALESCE(closed, CURRENT_DATE) - opened AS age_days
    FROM registers.ncr
    """,
    """
    CREATE VIEW registers.v_capa_register AS
    SELECT capa_id, opened, source_type, source_id, owner, status, description,
           root_cause, corrective_action, effectiveness_due,
           effectiveness_completed, closed,
           closed IS NULL AS is_open,
           COALESCE(closed, CURRENT_DATE) - opened AS age_days,
           effectiveness_completed IS NULL
               AND effectiveness_due < CURRENT_DATE AS effectiveness_overdue
    FROM registers.capa
    """,
    """
    CREATE VIEW registers.v_complaint_register AS
    SELECT complaint_id, received, device_model, lot, failure_category,
           description, investigation, risk_evaluated, risk_reference, mdr_id,
           status, closed,
           closed IS NULL AS is_open,
           COALESCE(closed, CURRENT_DATE) - received AS age_days
    FROM registers.complaint
    """,
    """
    CREATE VIEW registers.v_mdr_register AS
    SELECT mdr_id, complaint_id, submitted, event_type, device_model, lot,
           description
    FROM registers.mdr
    """,
    """
    CREATE VIEW registers.v_supplier_register AS
    SELECT supplier_id, name, commodity, approval_status, last_audit,
           audit_report_id,
           CURRENT_DATE - last_audit AS days_since_audit
    FROM registers.supplier
    """,
    """
    CREATE VIEW registers.v_supplier_audit_register AS
    SELECT report_id, supplier_id, audit_date, audit_type, result, findings
    FROM registers.supplier_audit
    """,
    """
    CREATE VIEW registers.v_fmea_register AS
    SELECT doc_key, row_id, item, "function", failure_mode, effect, cause,
           prevention_control, detection_control, severity, occurrence,
           detection, ap_recorded, ap_computed, ap_mismatch, risk_file_refs
    FROM registers.fmea_row
    """,
    """
    CREATE VIEW registers.v_trace_register AS
    SELECT req_id, category, requirement_text, design_outputs, protocols,
           reports, results, completed, has_verification
    FROM registers.requirement_trace
    """,
    """
    CREATE VIEW registers.v_training_register AS
    SELECT person, role, doc_key, revision, trained_on
    FROM registers.training
    """,
)

_VIEW_NAMES = (
    "v_ncr_register",
    "v_capa_register",
    "v_complaint_register",
    "v_mdr_register",
    "v_supplier_register",
    "v_supplier_audit_register",
    "v_fmea_register",
    "v_trace_register",
    "v_training_register",
)

_TABLE_NAMES = (
    "ncr",
    "capa",
    "complaint",
    "mdr",
    "supplier",
    "supplier_audit",
    "fmea_row",
    "requirement_trace",
    "training",
)


def upgrade() -> None:
    for statement in _TABLES + _VIEWS:
        op.execute(statement)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA registers TO gg_app")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA registers TO sql_tool_ro")


def downgrade() -> None:
    for view in _VIEW_NAMES:
        op.execute(f"DROP VIEW IF EXISTS registers.{view}")
    for table in _TABLE_NAMES:
        op.execute(f"DROP TABLE IF EXISTS registers.{table}")
