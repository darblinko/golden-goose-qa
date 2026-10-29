"""Ingestion registry: documents, document_versions, chunks.

app.documents is the logical controlled document (one row per doc_key such as
SOP-004 or CAPA-2025-007). app.document_versions is one row per distinct
content hash — re-ingestion of changed content always creates a new version,
never a silent overwrite. app.chunks stores parent and child chunks; children
are what gets indexed in Qdrant (point id == chunk id), parents are what the
generator reads.

Revision ID: 0002_ingestion_registry
Revises: 0001_baseline
"""

from alembic import op

revision = "0002_ingestion_registry"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_key text NOT NULL UNIQUE,
            doc_type text NOT NULL,
            title text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.document_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id uuid NOT NULL REFERENCES app.documents(id) ON DELETE CASCADE,
            content_hash text NOT NULL UNIQUE,
            revision text,
            status text NOT NULL DEFAULT 'effective'
                CHECK (status IN ('draft', 'effective', 'obsolete')),
            effective_from date,
            effective_to date,
            source_path text NOT NULL,
            file_format text NOT NULL,
            size_bytes bigint NOT NULL,
            object_key text NOT NULL,
            pipeline_state text NOT NULL DEFAULT 'registered'
                CHECK (pipeline_state IN (
                    'registered', 'parsed', 'chunked', 'indexed',
                    'skipped_unsupported', 'failed'
                )),
            failure_reason text,
            metrics jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_document_versions_document_id ON app.document_versions (document_id)"
    )
    op.execute(
        "CREATE INDEX ix_document_versions_pipeline_state ON app.document_versions (pipeline_state)"
    )

    op.execute(
        """
        CREATE TABLE app.chunks (
            id uuid PRIMARY KEY,
            document_version_id uuid NOT NULL
                REFERENCES app.document_versions(id) ON DELETE CASCADE,
            parent_id uuid REFERENCES app.chunks(id) ON DELETE CASCADE,
            ordinal integer NOT NULL,
            chunk_type text NOT NULL
                CHECK (chunk_type IN ('parent', 'child', 'row', 'page')),
            section_path text NOT NULL DEFAULT '',
            page integer,
            token_count integer NOT NULL,
            context_header text NOT NULL DEFAULT '',
            text text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (document_version_id, ordinal)
        )
        """
    )
    op.execute("CREATE INDEX ix_chunks_document_version_id ON app.chunks (document_version_id)")
    op.execute("CREATE INDEX ix_chunks_parent_id ON app.chunks (parent_id)")

    for table in ("app.documents", "app.document_versions", "app.chunks"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO gg_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.chunks")
    op.execute("DROP TABLE IF EXISTS app.document_versions")
    op.execute("DROP TABLE IF EXISTS app.documents")
