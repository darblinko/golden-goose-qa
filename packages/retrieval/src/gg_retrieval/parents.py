"""Parent-context expansion: read parent chunks from the registry."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_parents(session: AsyncSession, parent_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not parent_ids:
        return {}
    rows = await session.execute(
        text(
            """
            SELECT c.id, c.document_version_id, c.text, c.context_header,
                   c.section_path, c.page,
                   d.doc_key, d.doc_type, d.title, d.deleted_at,
                   v.revision, v.pipeline_state
            FROM app.chunks c
            JOIN app.document_versions v ON v.id = c.document_version_id
            JOIN app.documents d ON d.id = v.document_id
            WHERE c.id = ANY(CAST(:ids AS uuid[]))
            """
        ),
        {"ids": parent_ids},
    )
    return {
        str(r.id): {
            "version_id": str(r.document_version_id),
            "text": r.text,
            "context_header": r.context_header,
            "section_path": r.section_path,
            "page": r.page,
            "doc_key": r.doc_key,
            "doc_type": r.doc_type,
            "title": r.title,
            "revision": r.revision,
            # Lifecycle/identity fields: the parent fetch is the final currency
            # boundary — a point that slipped past the Qdrant filter must not be
            # cited if the registry says its document was deleted or its version
            # never finished indexing.
            "deleted_at": r.deleted_at,
            "pipeline_state": r.pipeline_state,
        }
        for r in rows
    }
