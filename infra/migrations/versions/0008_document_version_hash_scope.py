"""Scope document_versions content_hash uniqueness to the document.

0002 created ``content_hash text NOT NULL UNIQUE``, a global constraint: the
first doc_key to register a given byte-string claimed that hash for the whole
registry, so a second doc_key with identical bytes (a boilerplate form, an
empty template, a shared appendix) collided on insert and could never get its
own version, chunks, or vectors. Idempotency is per-document, not global —
re-ingesting the same bytes under the same doc_key must be a no-op, but the
same bytes under a different doc_key is a distinct controlled document.

This drops the global unique constraint and replaces it with a composite
UNIQUE (document_id, content_hash). The registry lookup in register_version is
scoped to match; chunk ids are seeded on (doc_key, content_hash, ordinal) so
the two documents' chunks and Qdrant points stay disjoint as well.

Revision ID: 0008_document_version_hash_scope
Revises: 0007_sql_tool_ro_views_only
"""

from alembic import op

revision = "0008_document_version_hash_scope"
down_revision = "0007_sql_tool_ro_views_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.document_versions "
        "DROP CONSTRAINT IF EXISTS document_versions_content_hash_key"
    )
    op.execute(
        "ALTER TABLE app.document_versions "
        "ADD CONSTRAINT document_versions_document_id_content_hash_key "
        "UNIQUE (document_id, content_hash)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE app.document_versions "
        "DROP CONSTRAINT IF EXISTS document_versions_document_id_content_hash_key"
    )
    op.execute(
        "ALTER TABLE app.document_versions "
        "ADD CONSTRAINT document_versions_content_hash_key UNIQUE (content_hash)"
    )
