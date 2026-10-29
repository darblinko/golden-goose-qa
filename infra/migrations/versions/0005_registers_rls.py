"""Row level security on the restricted register tables.

The SQL tool's guard already refuses complaint and MDR relations for roles
without restricted access; this adds the database's own enforcement so a
guard bug cannot leak rows. registers.complaint and registers.mdr get RLS
with two policies: gg_app keeps full access for derive rebuilds, and
sql_tool_ro sees rows only when the transaction-local gg.read_restricted
flag is 'on' — WarehouseTool sets it from the caller's role, and an unset
flag reads as off (fail closed). The complaint/MDR views become
security_invoker so the policy is evaluated against sql_tool_ro, not the
view owner.

Revision ID: 0005_registers_rls
Revises: 0004_registers
"""

from alembic import op

revision = "0005_registers_rls"
down_revision = "0004_registers"
branch_labels = None
depends_on = None

_RESTRICTED_TABLES = ("registers.complaint", "registers.mdr")
_RESTRICTED_VIEWS = ("registers.v_complaint_register", "registers.v_mdr_register")


def upgrade() -> None:
    for table in _RESTRICTED_TABLES:
        policy_suffix = table.split(".", 1)[1]
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY app_full_access_{policy_suffix} ON {table}"
            " TO gg_app USING (true) WITH CHECK (true)"
        )
        op.execute(
            f"CREATE POLICY restricted_read_{policy_suffix} ON {table}"
            " FOR SELECT TO sql_tool_ro"
            " USING (current_setting('gg.read_restricted', true) = 'on')"
        )
    for view in _RESTRICTED_VIEWS:
        op.execute(f"ALTER VIEW {view} SET (security_invoker = true)")


def downgrade() -> None:
    for view in _RESTRICTED_VIEWS:
        op.execute(f"ALTER VIEW {view} SET (security_invoker = false)")
    for table in _RESTRICTED_TABLES:
        policy_suffix = table.split(".", 1)[1]
        op.execute(f"DROP POLICY IF EXISTS restricted_read_{policy_suffix} ON {table}")
        op.execute(f"DROP POLICY IF EXISTS app_full_access_{policy_suffix} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
