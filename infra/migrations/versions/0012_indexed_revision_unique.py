"""Enforce one indexed version per document revision.

The pipeline refuses a version whose parsed revision another version already
carries, under the per-document ingest lock. This partial unique index is the
authoritative backstop: two indexed versions of one document can never share a
revision. Failed and in-progress rows are excluded, so a quarantined duplicate
stays recorded as data. Creating the index fails on a database that already
holds such a duplicate; resolve it before upgrading.

Revision ID: 0012_indexed_revision_unique
Revises: 0011_processing_config_hash
"""

from alembic import op

revision = "0012_indexed_revision_unique"
down_revision = "0011_processing_config_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_document_versions_indexed_revision "
        "ON app.document_versions (document_id, revision) "
        "WHERE pipeline_state = 'indexed' AND revision IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX app.uq_document_versions_indexed_revision")
