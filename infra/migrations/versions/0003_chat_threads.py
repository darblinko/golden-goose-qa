"""Chat threads and messages.

app.threads is owner-scoped conversation metadata; app.messages stores every
turn with the verdict, citations, and step trace the UI replays. LangGraph
checkpoint tables are managed by AsyncPostgresSaver.setup() inside the
existing `checkpoints` schema and are intentionally not defined here.

Revision ID: 0003_chat_threads
Revises: 0002_ingestion_registry
"""

from alembic import op

revision = "0003_chat_threads"
down_revision = "0002_ingestion_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.threads (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            owner text NOT NULL,
            title text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_threads_owner_updated ON app.threads (owner, updated_at DESC)")

    op.execute(
        """
        CREATE TABLE app.messages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            thread_id uuid NOT NULL REFERENCES app.threads(id) ON DELETE CASCADE,
            role text NOT NULL CHECK (role IN ('user', 'assistant')),
            content text NOT NULL,
            verdict text,
            citations jsonb NOT NULL DEFAULT '[]'::jsonb,
            trace jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_messages_thread_created ON app.messages (thread_id, created_at)")

    for table in ("app.threads", "app.messages"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO gg_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.messages")
    op.execute("DROP TABLE IF EXISTS app.threads")
