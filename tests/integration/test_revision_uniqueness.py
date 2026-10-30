"""The database refuses a second indexed version of a document under a
revision another indexed version already carries. The pipeline check runs
under the per-document lock; this index is the authoritative backstop."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_VERSION = """
INSERT INTO app.document_versions
    (document_id, content_hash, revision, source_path, file_format, size_bytes,
     object_key, pipeline_state)
VALUES (:d, :h, 'B', 'x/dup.docx', 'docx', 1, 'k', :state)
"""


async def test_two_indexed_versions_cannot_share_a_revision(app_engine: AsyncEngine):
    async with AsyncSession(app_engine) as session, session.begin():
        document_id = (
            await session.execute(
                text(
                    "INSERT INTO app.documents (doc_key, doc_type, title) "
                    "VALUES ('SOP-992', 'sop', 'Duplicate revision') RETURNING id"
                )
            )
        ).scalar_one()
        await session.execute(text(_VERSION), {"d": document_id, "h": "h1", "state": "indexed"})
        # A failed duplicate stays recordable as data.
        await session.execute(text(_VERSION), {"d": document_id, "h": "h2", "state": "failed"})
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    text(_VERSION), {"d": document_id, "h": "h3", "state": "indexed"}
                )
        await session.rollback()
