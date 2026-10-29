"""Record the processing config a version was indexed under.

Content-hash idempotency skips re-indexing bytes already processed. That is only
safe while the processing configuration is unchanged — the chunking parameters
that split the bytes and the embedding provider/model/dimensions that vectorize
them. This column stamps the hash of that configuration on a version when it is
indexed, so a later run under a changed configuration re-chunks and re-embeds
instead of reporting the stale version unchanged. A NULL means "indexed before
this column existed"; such a version does not match any current config and is
rebuilt once, which converges the collection onto the current configuration.

Revision ID: 0011_processing_config_hash
Revises: 0010_message_access_level
"""

from alembic import op

revision = "0011_processing_config_hash"
down_revision = "0010_message_access_level"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.document_versions ADD COLUMN processing_config_hash text")


def downgrade() -> None:
    op.execute("ALTER TABLE app.document_versions DROP COLUMN processing_config_hash")
