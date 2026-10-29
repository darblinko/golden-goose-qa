"""Tombstone column for retired source documents.

When a source is deleted at its origin (a connector listing drops it), the
document must stop being retrievable and citable — but the fact that it once
existed, and when it was withdrawn, is itself an auditable QMS event. So a
retirement is a soft delete: app.documents.deleted_at is stamped, the row is
kept, and every reader that serves present state (the source viewer, the
graph/warehouse derive) filters deleted_at IS NULL. The retrievable
projections (vector points, chunk rows) are removed by the retire operation
itself; only the registry rows persist as the tombstone.

Revision ID: 0009_document_soft_delete
Revises: 0008_document_version_hash_scope
"""

from alembic import op

revision = "0009_document_soft_delete"
down_revision = "0008_document_version_hash_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.documents ADD COLUMN deleted_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE app.documents DROP COLUMN deleted_at")
