"""Per-message access level for thread replay.

A stored assistant message can contain restricted-record text (a QA user asked
about a complaint narrative). Whether the current reader may see it must be
re-decided every time the thread is replayed, not at write time only — the same
subject can be downgraded from qa_user to auditor_readonly between turns. So the
level the message was written at is persisted next to it, and the read path
redacts any message whose level the reader's role no longer allows.

The column is fail-closed: NOT NULL, DEFAULT 'restricted', so a row inserted
without an explicit level is hidden from unprivileged readers rather than
leaked. The backfill mirrors gg_common.acl (RESTRICTED_DOC_TYPES +
is_restricted_key over doc_key and source_doc_keys): existing rows are marked
'general' only when no citation references a restricted family or record key.

Revision ID: 0010_message_access_level
Revises: 0009_document_soft_delete
"""

from alembic import op

revision = "0010_message_access_level"
down_revision = "0009_document_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.messages ADD COLUMN access_level text NOT NULL "
        "DEFAULT 'restricted' CHECK (access_level IN ('general', 'restricted'))"
    )
    # The default stamped every existing row 'restricted'; relax only rows whose
    # every citation is provably general. Fail-closed like gg_common.acl: a
    # citation counts against the row (keeps it restricted) if it has a restricted
    # family/key OR its doc_type is neither a known-general family nor a synthetic
    # tool/external result — an unknown or missing doc_type stays restricted. A
    # missing doc_type is coalesced to '' so NOT IN yields TRUE, not NULL.
    op.execute(
        """
        UPDATE app.messages SET access_level = 'general'
        WHERE NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(citations) AS citation
            WHERE upper(citation->>'doc_key') LIKE 'C-%'
               OR upper(citation->>'doc_key') LIKE 'MDR-%'
               OR upper(citation->>'doc_key') LIKE 'EMDR-%'
               OR EXISTS (
                   SELECT 1 FROM jsonb_array_elements_text(
                       COALESCE(citation->'source_doc_keys', '[]'::jsonb)
                   ) AS source_key
                   WHERE upper(source_key) LIKE 'C-%'
                      OR upper(source_key) LIKE 'MDR-%'
                      OR upper(source_key) LIKE 'EMDR-%'
               )
               OR COALESCE(citation->>'doc_type', '') NOT IN (
                   'tool_result', 'external_result',
                   'quality_manual', 'sop', 'wi', 'design_input', 'design_plan',
                   'risk_plan', 'risk_analysis', 'risk_report', 'trace_matrix',
                   'dfmea', 'pfmea', 'training_matrix', 'supplier_list',
                   'supplier_audit', 'internal_audit', 'management_review',
                   'clinical_plan', 'clinical_report', 'control_plan', 'capa',
                   'ncr', 'verification_report', 'dhr', 'dhr_scanned'
               )
        )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app.messages DROP COLUMN access_level")
