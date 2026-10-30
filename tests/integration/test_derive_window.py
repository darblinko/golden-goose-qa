"""Derivation projects only the version in force today. A document whose
only indexed version takes effect in the future has no eligible version and
must be left out of the graph and registers, rather than projected early."""

from datetime import date

import pytest
from gg_ingestion.extract.derive import indexed_documents
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration


async def _insert(session: AsyncSession, doc_key: str, effective_from: date) -> None:
    document_id = (
        await session.execute(
            text(
                "INSERT INTO app.documents (doc_key, doc_type, title) "
                "VALUES (:k, 'sop', 'Future procedure') RETURNING id"
            ),
            {"k": doc_key},
        )
    ).scalar_one()
    await session.execute(
        text(
            """
            INSERT INTO app.document_versions
                (document_id, content_hash, revision, source_path, file_format,
                 size_bytes, object_key, pipeline_state, status, effective_from)
            VALUES (:d, :h, 'A', 'x/future.docx', 'docx', 1, 'k', 'indexed',
                    'effective', :f)
            """
        ),
        {"d": document_id, "h": f"hash-{doc_key}", "f": effective_from},
    )


async def test_future_only_document_is_not_derived(app_engine: AsyncEngine):
    async with AsyncSession(app_engine) as session, session.begin():
        await _insert(session, "SOP-990", date(2027, 1, 1))
        await _insert(session, "SOP-991", date(2026, 1, 1))
        selected = {
            doc.doc_key for doc in await indexed_documents(session, today=date(2026, 10, 1))
        }
        await session.rollback()
    assert "SOP-991" in selected
    assert "SOP-990" not in selected
