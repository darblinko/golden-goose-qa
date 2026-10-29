"""Thread and message persistence. Every query is owner-scoped: a thread id
from another user behaves exactly like a missing thread (404, never 403 —
existence is not leaked)."""

import json
from typing import Any

from gg_common.acl import message_access_level, role_can_read_access_level
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_TITLE_CHARS = 80

# Shown in place of a redacted message's content on replay after a role
# downgrade. The turn stays in the thread (its existence is not secret); only
# the restricted text and its citations are withheld.
REDACTED_NOTICE = (
    "[Redacted: this message contains restricted content your current role cannot view.]"
)


async def create_thread(session: AsyncSession, *, owner: str, title: str) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "INSERT INTO app.threads (owner, title) VALUES (:owner, :title) "
                "RETURNING id, title, created_at, updated_at"
            ),
            {"owner": owner, "title": title},
        )
    ).one()
    return _thread_dict(row)


async def list_threads(session: AsyncSession, *, owner: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, title, created_at, updated_at FROM app.threads "
                "WHERE owner = :owner ORDER BY updated_at DESC"
            ),
            {"owner": owner},
        )
    ).all()
    return [_thread_dict(row) for row in rows]


async def get_thread(session: AsyncSession, *, thread_id: str, owner: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT id, title, created_at, updated_at FROM app.threads "
                "WHERE id = CAST(:id AS uuid) AND owner = :owner"
            ),
            {"id": thread_id, "owner": owner},
        )
    ).one_or_none()
    return _thread_dict(row) if row else None


async def delete_thread(session: AsyncSession, *, thread_id: str, owner: str) -> bool:
    row = (
        await session.execute(
            text(
                "DELETE FROM app.threads WHERE id = CAST(:id AS uuid) AND owner = :owner "
                "RETURNING id"
            ),
            {"id": thread_id, "owner": owner},
        )
    ).one_or_none()
    return row is not None


async def add_message(
    session: AsyncSession,
    *,
    thread_id: str,
    role: str,
    content: str,
    verdict: str | None = None,
    citations: list[dict[str, Any]] | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    access_level = message_access_level(citations or [])
    row = (
        await session.execute(
            text(
                "INSERT INTO app.messages "
                "(thread_id, role, content, verdict, citations, trace, access_level) "
                "VALUES (CAST(:thread_id AS uuid), :role, :content, :verdict, "
                "CAST(:citations AS jsonb), CAST(:trace AS jsonb), :access_level) "
                "RETURNING id, role, content, verdict, citations, trace, access_level, created_at"
            ),
            {
                "thread_id": thread_id,
                "role": role,
                "content": content,
                "verdict": verdict,
                "citations": json.dumps(citations or [], default=str),
                "trace": json.dumps(trace or [], default=str),
                "access_level": access_level,
            },
        )
    ).one()
    await session.execute(
        text(
            "UPDATE app.threads SET updated_at = now(), "
            "title = CASE WHEN title = '' THEN :title ELSE title END "
            "WHERE id = CAST(:thread_id AS uuid)"
        ),
        {"thread_id": thread_id, "title": content[:_TITLE_CHARS]},
    )
    return _message_dict(row)


async def list_messages(session: AsyncSession, *, thread_id: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, role, content, verdict, citations, trace, access_level, created_at "
                "FROM app.messages WHERE thread_id = CAST(:thread_id AS uuid) ORDER BY created_at, id"
            ),
            {"thread_id": thread_id},
        )
    ).all()
    return [_message_dict(row) for row in rows]


def redact_message_for_role(message: dict[str, Any], role: str) -> dict[str, Any]:
    """Return the message as this role may see it. A message stored above the
    role's access level (a QA turn replayed after a downgrade to auditor) keeps
    its position and metadata but has its restricted content, citations, and
    trace withheld. Returns a new dict; the stored row is never mutated."""
    if role_can_read_access_level(role, message.get("access_level", "restricted")):
        return {**message, "redacted": False}
    return {
        **message,
        "content": REDACTED_NOTICE,
        "citations": [],
        "trace": [],
        "redacted": True,
    }


async def recent_history(
    session: AsyncSession, *, thread_id: str, role: str, limit: int = 6
) -> list[dict[str, str]]:
    """Last turns as {role, content} pairs for the agent's history window,
    filtered to what this role may read: a downgraded caller's own prior
    restricted turns must not re-enter the prompt as context."""
    messages = await list_messages(session, thread_id=thread_id)
    readable = [
        m for m in messages if role_can_read_access_level(role, m.get("access_level", "restricted"))
    ]
    return [{"role": m["role"], "content": m["content"]} for m in readable[-limit:]]


def _thread_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _message_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "role": row.role,
        "content": row.content,
        "verdict": row.verdict,
        "citations": row.citations,
        "trace": row.trace,
        "access_level": row.access_level,
        "created_at": row.created_at.isoformat(),
    }
