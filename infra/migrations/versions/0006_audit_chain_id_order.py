"""Audit chain: assign id inside the trigger so id order equals chain order.

The identity column assigned ids before the BEFORE INSERT trigger ran, so two
concurrent inserts could acquire the chain advisory lock in the opposite order
to their pre-assigned ids. The trigger locates the chain head with ORDER BY id
DESC, so the later lock holder could link to a row that was not the true head,
forking the chain. Assigning the id under the lock makes id order, lock order,
and chain order identical by construction; the hash material is unchanged.
"""

from alembic import op

revision = "0006_audit_chain_id_order"
down_revision = "0005_registers_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit.audit_log ALTER COLUMN id DROP IDENTITY IF EXISTS")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit.chain_hash() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            last_id bigint;
            last_hash bytea;
            ts_text text;
            material bytea;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('audit.audit_log')::bigint);
            SELECT id, row_hash INTO last_id, last_hash
            FROM audit.audit_log ORDER BY id DESC LIMIT 1;
            IF last_id IS NULL THEN
                last_id := 0;
                last_hash := decode(repeat('00', 32), 'hex');
            END IF;
            NEW.id := last_id + 1;
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


def downgrade() -> None:
    raise RuntimeError(
        "Downgrading would reintroduce the concurrent-insert chain fork; "
        "the audit chain contract is never downgraded."
    )
