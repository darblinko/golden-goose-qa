"""sql_tool_ro reads the curated views only (ADR-0015 made true).

0001 default privileges and 0004's blanket ``GRANT SELECT ON ALL TABLES``
gave sql_tool_ro SELECT on every relation in schema registers, including the
raw base tables. The SQL guard's whitelist already refuses the base tables,
but ADR-0015 promises the database enforces the same boundary, so a whitelist
expansion or guard bug cannot read unguarded records directly.

This scopes the read role to exactly the nine ``registers.v_*`` views. The two
restricted views (v_complaint_register, v_mdr_register) are ``security_invoker``
over RLS base tables (0005), so sql_tool_ro must keep SELECT on
registers.complaint and registers.mdr for the policy to be evaluated as the
invoking role — those rows stay gated by the restricted_read policy, which
fails closed on an unset gg.read_restricted flag. The other seven base tables
lose direct access entirely. The default-privilege rule that auto-granted new
base tables to the read role is reversed; views are granted explicitly.

Revision ID: 0007_sql_tool_ro_views_only
Revises: 0006_audit_chain_id_order
"""

from alembic import op

revision = "0007_sql_tool_ro_views_only"
down_revision = "0006_audit_chain_id_order"
branch_labels = None
depends_on = None

# The entire curated surface the read role may query.
_VIEWS = (
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

# Base tables the read role must not reach directly. complaint and mdr are
# intentionally absent: their security_invoker views require the invoking role
# to hold SELECT on the RLS-protected base table, which the restricted_read
# policy then filters row-by-row.
_REVOKED_TABLES = (
    "ncr",
    "capa",
    "supplier",
    "supplier_audit",
    "fmea_row",
    "requirement_trace",
    "training",
)


def upgrade() -> None:
    # Stop new registers tables from auto-granting SELECT to the read role.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA registers REVOKE SELECT ON TABLES FROM sql_tool_ro"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE gg_app IN SCHEMA registers "
        "REVOKE SELECT ON TABLES FROM sql_tool_ro"
    )
    # Remove direct access to the unguarded base tables.
    for table in _REVOKED_TABLES:
        op.execute(f"REVOKE SELECT ON registers.{table} FROM sql_tool_ro")
    # Grant SELECT on exactly the nine curated views (idempotent re-grant).
    for view in _VIEWS:
        op.execute(f"GRANT SELECT ON registers.{view} TO sql_tool_ro")


def downgrade() -> None:
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA registers GRANT SELECT ON TABLES TO sql_tool_ro")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE gg_app IN SCHEMA registers "
        "GRANT SELECT ON TABLES TO sql_tool_ro"
    )
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA registers TO sql_tool_ro")
