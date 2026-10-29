"""Baseline: schemas, roles, append-only hash-chained audit log.

The trigger's hash material MUST stay byte-identical to
gg_common.audit.compute_row_hash:
    sha256(prev_hash || '|' || actor || '|' || action || '|' || payload::text
           || '|' || to_char(occurred_at AT TIME ZONE 'UTC',
                             'YYYY-MM-DD"T"HH24:MI:SS.US"+00"'))
with a genesis prev_hash of 32 zero bytes. Change either side only together.

Revision ID: 0001_baseline
Revises: None
"""

from alembic import op
from gg_common.settings import PostgresSettings

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _sql_literal(value: str) -> str:
    """A single-quoted SQL string literal with embedded quotes escaped. Safe
    with standard_conforming_strings (Postgres default), so a password carrying
    a quote cannot break out of the literal."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _sql_identifier(value: str) -> str:
    """A double-quoted SQL identifier with embedded quotes escaped, so a
    database name cannot inject beyond the identifier position."""
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def upgrade() -> None:
    pg = PostgresSettings()
    app_password = _sql_literal(pg.password.get_secret_value())
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gg_app') THEN
                CREATE ROLE gg_app LOGIN PASSWORD {app_password};
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sql_tool_ro') THEN
                CREATE ROLE sql_tool_ro NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT sql_tool_ro TO gg_app")

    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("CREATE SCHEMA IF NOT EXISTS registers")
    op.execute("CREATE SCHEMA IF NOT EXISTS checkpoints")
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")

    op.execute(f"GRANT ALL ON DATABASE {_sql_identifier(pg.database)} TO gg_app")
    op.execute("GRANT USAGE, CREATE ON SCHEMA app TO gg_app")
    op.execute("GRANT USAGE, CREATE ON SCHEMA registers TO gg_app")
    op.execute("GRANT USAGE, CREATE ON SCHEMA checkpoints TO gg_app")
    op.execute("GRANT USAGE ON SCHEMA audit TO gg_app")
    op.execute("GRANT USAGE ON SCHEMA registers TO sql_tool_ro")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA registers GRANT SELECT ON TABLES TO sql_tool_ro")
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE gg_app IN SCHEMA registers "
        "GRANT SELECT ON TABLES TO sql_tool_ro"
    )

    op.execute(
        """
        CREATE TABLE audit.audit_log (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            actor text NOT NULL,
            action text NOT NULL,
            payload jsonb NOT NULL,
            prev_hash bytea NOT NULL,
            row_hash bytea NOT NULL
        )
        """
    )

    op.execute(
        """
        CREATE FUNCTION audit.chain_hash() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            last_hash bytea;
            ts_text text;
            material bytea;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('audit.audit_log')::bigint);
            SELECT row_hash INTO last_hash
            FROM audit.audit_log ORDER BY id DESC LIMIT 1;
            IF last_hash IS NULL THEN
                last_hash := decode(repeat('00', 32), 'hex');
            END IF;
            IF NEW.occurred_at IS NULL THEN
                NEW.occurred_at := now();
            END IF;
            ts_text := to_char(
                NEW.occurred_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"+00"'
            );
            material := last_hash
                || convert_to('|' || NEW.actor || '|' || NEW.action || '|', 'UTF8')
                || convert_to(NEW.payload::text, 'UTF8')
                || convert_to('|' || ts_text, 'UTF8');
            NEW.prev_hash := last_hash;
            NEW.row_hash := sha256(material);
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_chain
        BEFORE INSERT ON audit.audit_log
        FOR EACH ROW EXECUTE FUNCTION audit.chain_hash()
        """
    )

    op.execute(
        """
        CREATE FUNCTION audit.reject_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit.audit_log is append-only: % is not permitted', TG_OP;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_mutation
        BEFORE UPDATE OR DELETE ON audit.audit_log
        FOR EACH ROW EXECUTE FUNCTION audit.reject_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_truncate
        BEFORE TRUNCATE ON audit.audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION audit.reject_mutation()
        """
    )

    op.execute("REVOKE ALL ON audit.audit_log FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT ON audit.audit_log TO gg_app")


def downgrade() -> None:
    raise RuntimeError(
        "The baseline (audit log included) is never downgraded; restore from backup instead."
    )
