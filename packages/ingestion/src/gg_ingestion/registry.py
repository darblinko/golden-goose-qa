"""Document registry repository over app.documents / document_versions / chunks.

Content hash is the idempotency key within one document: the same bytes under
the same doc_key are never registered twice, and changed bytes for the same
doc_key always become a new version row. Uniqueness is (document_id,
content_hash), so two different doc_keys that share identical bytes each get
their own version rather than the second aliasing the first.
"""

import itertools
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from gg_ingestion.models import Chunk, DocMeta

PIPELINE_STATES = (
    "registered",
    "parsed",
    "chunked",
    "indexed",
    "skipped_unsupported",
    "failed",
)

# Namespace for the ingestion document-key advisory lock. The two-int form of
# pg_advisory_xact_lock (class, object) keeps this lock in its own space so it
# cannot collide with any other advisory lock in the database; the object key is
# hashtext(doc_key). An arbitrary fixed int4 that identifies "ingestion".
_INGEST_LOCK_CLASS = 0x6767_4947  # "ggIG"


@dataclass(frozen=True)
class RegisteredVersion:
    document_id: str
    version_id: str
    content_hash: str
    doc_key: str
    created: bool
    # The document was retired (deleted_at set) before this registration; it is
    # restored only once this version is indexed again.
    tombstoned: bool = False


@dataclass(frozen=True)
class SourceVersion:
    """The servable original behind a cited doc_key: enough to locate the
    bytes (object_key), verify them (content_hash), classify access (doc_type),
    and label the download (title/revision/file_format)."""

    version_id: str
    doc_key: str
    doc_type: str
    title: str | None
    revision: str | None
    file_format: str
    content_hash: str
    object_key: str


@dataclass(frozen=True)
class VersionLifecycle:
    version_id: str
    effective_from: date | None
    created_at: datetime
    status: str
    effective_to: date | None


@dataclass(frozen=True)
class SupersedePlan:
    version_id: str
    status: str
    effective_to: date | None


def parse_effective_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d-%b-%Y").date()
    except ValueError:
        return None


class RevisionConflictError(RuntimeError):
    """A new version of a document reuses a revision label already carried by a
    different version. Two distinct byte contents under one revision make the
    'revision in effect' ambiguous and would let a re-index silently rewrite the
    historical record, so the second one is refused rather than published."""


def find_revision_conflict(
    existing: Sequence[tuple[str, str | None]], version_id: str, revision: str | None
) -> str | None:
    """Return the version_id of another version of the same document that
    already carries `revision`, or None when the revision is free to use. A
    null/empty revision never conflicts — unrevised records and templates may
    legitimately coexist; only a concrete, repeated revision label is refused.
    The version being applied is excluded so a retry of the same version (its
    own revision unchanged) is always allowed."""
    if not revision:
        return None
    for other_id, other_revision in existing:
        if other_id != version_id and other_revision == revision:
            return other_id
    return None


async def assert_unique_revision(
    session: AsyncSession, *, document_id: str, version_id: str, revision: str | None
) -> None:
    """Fail closed if another version of this document already owns `revision`.
    Called once the authoritative (parsed) revision is known, before the version
    is indexed, so a repeated revision identity is quarantined as a failed
    version instead of corrupting the document's history."""
    rows = await session.execute(
        text("SELECT id, revision FROM app.document_versions WHERE document_id = :d"),
        {"d": document_id},
    )
    existing = [(str(row.id), row.revision) for row in rows]
    conflict = find_revision_conflict(existing, version_id, revision)
    if conflict is not None:
        raise RevisionConflictError(
            f"revision {revision!r} already belongs to version {conflict} of this "
            f"document; refusing to publish a second version under the same revision"
        )


async def register_version(
    session: AsyncSession,
    *,
    meta: DocMeta,
    content_hash: str,
    source_path: str,
    size_bytes: int,
    object_key: str,
) -> RegisteredVersion:
    # Serialize all registration and version creation for this document key.
    # Without it, two concurrent ingests of the same source both pass the
    # version-existence check below and both insert, forking the document's
    # version history. A transaction-scoped advisory lock releases automatically
    # at commit or rollback, so no explicit unlock is needed on any path.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_class, hashtext(:doc_key))"),
        {"lock_class": _INGEST_LOCK_CLASS, "doc_key": meta.doc_key},
    )
    row = (
        await session.execute(
            text(
                """
                INSERT INTO app.documents (doc_key, doc_type, title)
                VALUES (:doc_key, :doc_type, :title)
                ON CONFLICT (doc_key) DO UPDATE
                    SET doc_type = EXCLUDED.doc_type,
                        title = EXCLUDED.title,
                        updated_at = now()
                RETURNING id, deleted_at IS NOT NULL AS tombstoned
                """
            ),
            {"doc_key": meta.doc_key, "doc_type": meta.doc_type, "title": meta.title},
        )
    ).one()
    document_id = str(row.id)
    tombstoned = bool(row.tombstoned)

    # Scope the idempotency lookup to this document: two distinct doc_keys may
    # legitimately share identical bytes (a boilerplate form, an empty template),
    # and each must get its own version, chunks, and vectors rather than the
    # second silently aliasing the first.
    existing = (
        await session.execute(
            text(
                "SELECT id FROM app.document_versions "
                "WHERE document_id = :document_id AND content_hash = :h"
            ),
            {"document_id": document_id, "h": content_hash},
        )
    ).first()
    if existing:
        return RegisteredVersion(
            document_id=document_id,
            version_id=str(existing.id),
            content_hash=content_hash,
            doc_key=meta.doc_key,
            created=False,
            tombstoned=tombstoned,
        )

    version = (
        await session.execute(
            text(
                """
                INSERT INTO app.document_versions
                    (document_id, content_hash, revision, source_path,
                     file_format, size_bytes, object_key)
                VALUES (:document_id, :content_hash, :revision, :source_path,
                        :file_format, :size_bytes, :object_key)
                RETURNING id
                """
            ),
            {
                "document_id": document_id,
                "content_hash": content_hash,
                "revision": meta.revision,
                "source_path": source_path,
                "file_format": meta.file_format,
                "size_bytes": size_bytes,
                "object_key": object_key,
            },
        )
    ).one()
    return RegisteredVersion(
        document_id=document_id,
        version_id=str(version.id),
        content_hash=content_hash,
        doc_key=meta.doc_key,
        created=True,
        tombstoned=tombstoned,
    )


async def restore_document(session: AsyncSession, *, document_id: str, version_id: str) -> bool:
    """Clear a retired document's tombstone once `version_id` is indexed again.

    Retirement removed every revision's chunks and points, so the other
    versions return to 'registered': they are reindexed when their files are
    ingested again, instead of counting as indexed with no searchable content.
    Returns True when a tombstone was cleared."""
    cleared = (
        await session.execute(
            text(
                "UPDATE app.documents SET deleted_at = NULL, updated_at = now() "
                "WHERE id = :document_id AND deleted_at IS NOT NULL RETURNING id"
            ),
            {"document_id": document_id},
        )
    ).first()
    if cleared is None:
        return False
    await session.execute(
        text(
            "UPDATE app.document_versions SET pipeline_state = 'registered', updated_at = now() "
            "WHERE document_id = :document_id AND id <> :version_id "
            "AND pipeline_state = 'indexed'"
        ),
        {"document_id": document_id, "version_id": version_id},
    )
    return True


async def resolve_doc_keys_by_source_paths(
    session: AsyncSession, source_paths: Sequence[str]
) -> dict[str, str]:
    """Map each source path to the doc_key of the live (non-tombstoned) document
    whose version was ingested from it. Paths with no live binding are absent
    from the result. Used by sync reconciliation to tell a rename (a deleted
    path whose doc_key reappears under a new path) from a genuine removal, before
    anything is retired. An empty batch issues no query."""
    if not source_paths:
        return {}
    rows = await session.execute(
        text(
            """
            SELECT v.source_path AS source_path, d.doc_key AS doc_key
            FROM app.document_versions v
            JOIN app.documents d ON d.id = v.document_id
            WHERE v.source_path = ANY(:source_paths) AND d.deleted_at IS NULL
            """
        ),
        {"source_paths": list(source_paths)},
    )
    return {row.source_path: row.doc_key for row in rows}


async def rebind_source_path(
    session: AsyncSession, *, old_source_path: str, new_source_path: str
) -> None:
    """Move a document's source binding after a source-side rename/move of
    unchanged bytes. The content-hash short-circuit reports the moved file
    unchanged without touching source_path, so the binding would otherwise still
    name the vanished path — leaving the document unreachable for a future
    retirement. Rebinding keeps the live document retirable under where it now
    lives."""
    await session.execute(
        text(
            "UPDATE app.document_versions "
            "SET source_path = :new, updated_at = now() "
            "WHERE source_path = :old"
        ),
        {"new": new_source_path, "old": old_source_path},
    )


async def fetch_source_version(
    session: AsyncSession, *, doc_key: str, version_id: str | None = None
) -> SourceVersion | None:
    """Resolve the original a citation points to. With version_id, resolve that
    exact version so a citation to an obsolete revision serves the revision that
    was cited, not the current one. Without it, resolve the current effective
    version, falling back to the most recently created indexed version when none
    is marked effective. Only indexed versions are servable — a failed, skipped,
    or still-parsing row has no trustworthy original to show. Returns None when
    the document (or the requested indexed version of it) is unknown."""
    version_clause = "AND v.id = CAST(:version_id AS uuid)" if version_id else ""
    row = (
        await session.execute(
            text(
                f"""
                SELECT v.id, d.doc_key, d.doc_type, d.title, v.revision,
                       v.file_format, v.content_hash, v.object_key
                FROM app.document_versions v
                JOIN app.documents d ON d.id = v.document_id
                WHERE d.doc_key = :doc_key AND v.pipeline_state = 'indexed'
                      AND d.deleted_at IS NULL
                      {version_clause}
                ORDER BY (v.status = 'effective') DESC,
                         v.effective_from DESC NULLS LAST,
                         v.created_at DESC
                LIMIT 1
                """
            ),
            {"doc_key": doc_key, "version_id": version_id},
        )
    ).first()
    if row is None:
        return None
    return SourceVersion(
        version_id=str(row.id),
        doc_key=row.doc_key,
        doc_type=row.doc_type,
        title=row.title,
        revision=row.revision,
        file_format=row.file_format,
        content_hash=row.content_hash,
        object_key=row.object_key,
    )


async def update_version(
    session: AsyncSession,
    version_id: str,
    *,
    pipeline_state: str,
    revision: str | None = None,
    effective_from: date | None = None,
    failure_reason: str | None = None,
    metrics: dict[str, Any] | None = None,
    processing_config_hash: str | None = None,
) -> None:
    if pipeline_state not in PIPELINE_STATES:
        raise ValueError(f"unknown pipeline_state: {pipeline_state}")
    await session.execute(
        text(
            """
            UPDATE app.document_versions
            SET pipeline_state = :state,
                revision = COALESCE(:revision, revision),
                effective_from = COALESCE(:effective_from, effective_from),
                failure_reason = :failure_reason,
                metrics = COALESCE(CAST(:metrics AS jsonb), metrics),
                processing_config_hash =
                    COALESCE(:processing_config_hash, processing_config_hash),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": version_id,
            "state": pipeline_state,
            "revision": revision,
            "effective_from": effective_from,
            "failure_reason": failure_reason,
            "metrics": json.dumps(metrics) if metrics is not None else None,
            "processing_config_hash": processing_config_hash,
        },
    )


async def replace_chunks(session: AsyncSession, version_id: str, chunks: list[Chunk]) -> None:
    """Delete-then-insert keeps Postgres consistent with the Qdrant
    delete-before-upsert for the same version."""
    await session.execute(
        text("DELETE FROM app.chunks WHERE document_version_id = :v"), {"v": version_id}
    )
    parents = [c for c in chunks if c.chunk_type == "parent"]
    children = [c for c in chunks if c.chunk_type != "parent"]
    for batch in (parents, children):
        for chunk in batch:
            await session.execute(
                text(
                    """
                    INSERT INTO app.chunks
                        (id, document_version_id, parent_id, ordinal, chunk_type,
                         section_path, page, token_count, context_header, text, payload)
                    VALUES (:id, :version_id, :parent_id, :ordinal, :chunk_type,
                            :section_path, :page, :token_count, :context_header,
                            :text, CAST(:payload AS jsonb))
                    """
                ),
                {
                    "id": chunk.chunk_id,
                    "version_id": version_id,
                    "parent_id": chunk.parent_id,
                    "ordinal": chunk.ordinal,
                    "chunk_type": chunk.chunk_type,
                    "section_path": chunk.section_path,
                    "page": chunk.page,
                    "token_count": chunk.token_count,
                    "context_header": chunk.context_header,
                    "text": chunk.text,
                    "payload": json.dumps(chunk.payload),
                },
            )


def plan_supersessions(
    versions: list[VersionLifecycle], today: date | None = None
) -> list[SupersedePlan]:
    """Compute lifecycle transitions for one document's indexed versions.

    Every version is closed at its successor's effective date, so the
    [effective_from, effective_to) windows never overlap. A version becomes
    obsolete only once its successor is in force (successor undated, or dated
    on or before `today`); a revision published ahead of its effective date
    leaves its predecessor effective until then. Retrieval and derivation
    select by the window, so they agree on the revision in force on any date.
    Only versions whose recorded state differs are returned."""
    if len(versions) < 2:
        return []
    today = today or date.today()
    ordered = sorted(
        versions, key=lambda v: (v.effective_from or date.min, v.created_at, v.version_id)
    )
    plans = []
    for version, successor in itertools.pairwise(ordered):
        successor_in_force = successor.effective_from is None or successor.effective_from <= today
        target = SupersedePlan(
            version_id=version.version_id,
            status="obsolete" if successor_in_force else "effective",
            effective_to=successor.effective_from,
        )
        if (version.status, version.effective_to) != (target.status, target.effective_to):
            plans.append(target)
    current = ordered[-1]
    if (current.status, current.effective_to) != ("effective", None):
        plans.append(
            SupersedePlan(version_id=current.version_id, status="effective", effective_to=None)
        )
    return plans


async def reconcile_document_versions(
    session: AsyncSession, document_id: str
) -> list[SupersedePlan]:
    """Apply plan_supersessions to the registry rows; the caller mirrors the
    returned plans onto the search index payloads."""
    rows = await session.execute(
        text(
            """
            SELECT id, effective_from, created_at, status, effective_to
            FROM app.document_versions
            WHERE document_id = :document_id AND pipeline_state = 'indexed'
            """
        ),
        {"document_id": document_id},
    )
    versions = [
        VersionLifecycle(
            version_id=str(row.id),
            effective_from=row.effective_from,
            created_at=row.created_at,
            status=row.status,
            effective_to=row.effective_to,
        )
        for row in rows
    ]
    plans = plan_supersessions(versions)
    for plan in plans:
        await session.execute(
            text(
                """
                UPDATE app.document_versions
                SET status = :status, effective_to = :effective_to, updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": plan.version_id, "status": plan.status, "effective_to": plan.effective_to},
        )
    return plans


async def pipeline_summary(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(
        text(
            "SELECT pipeline_state, count(*) AS n FROM app.document_versions "
            "GROUP BY pipeline_state ORDER BY pipeline_state"
        )
    )
    return {r.pipeline_state: r.n for r in rows}
