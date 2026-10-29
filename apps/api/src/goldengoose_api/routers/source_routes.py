"""Source viewer: serve the original bytes behind a cited document.

A citation names a doc_key; this route returns the original file for that
document's current version, but only after two independent checks:

- Access control: the same fail-closed doc-type classification the retrieval
  and SQL paths use (`gg_common.acl`). An auditor_readonly caller never
  receives the content of a restricted family (complaint, MDR, eMDR) even by
  asking for it directly by key.
- Integrity: the bytes are re-hashed and compared against the content hash the
  registry recorded at ingestion. The object store is not trusted as the
  source of truth; a mismatch fails closed rather than serving possibly
  corrupt or tampered content.
"""

import logging
import re

from fastapi import APIRouter, HTTPException, Request, Response
from gg_common.acl import access_level_for, allowed_access_levels
from gg_common.objectstore import ObjectIntegrityError, read_verified
from gg_ingestion.registry import fetch_source_version

from goldengoose_api.auth import CurrentUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources", tags=["sources"])

# Conservative content types for the formats the ingestion router accepts;
# anything else downloads as an opaque stream rather than being guessed.
_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xml": "application/xml",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
}

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")


@router.get("/{doc_key}")
async def get_source(
    request: Request, doc_key: str, user: CurrentUser, version: str | None = None
) -> Response:
    # `version` (a document_version id) pins the download to the exact revision a
    # citation named. Without it the current effective version is served — which
    # would mismatch a citation to a superseded revision.
    state = request.app.state
    async with state.session_factory() as session:
        source = await fetch_source_version(session, doc_key=doc_key, version_id=version)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    if access_level_for(source.doc_type) not in allowed_access_levels(user.role):
        raise HTTPException(status_code=403, detail="not authorized for this document")

    try:
        data = read_verified(
            state.object_store,
            state.settings.objectstore.bucket_documents,
            source.object_key,
            expected_sha256=source.content_hash,
        )
    except ObjectIntegrityError:
        # The stored original does not match the registry hash; refuse to serve
        # it rather than hand back possibly tampered evidence.
        logger.error("source integrity check failed for %s (%s)", doc_key, source.object_key)
        raise HTTPException(
            status_code=500, detail="source failed integrity verification"
        ) from None

    media_type = _CONTENT_TYPES.get(source.file_format, "application/octet-stream")
    safe_key = _UNSAFE_FILENAME_CHARS.sub("_", source.doc_key)
    filename = f"{safe_key}.{source.file_format}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
