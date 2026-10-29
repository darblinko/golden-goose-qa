"""Audit log writer. The hash chain and append-only guarantees are enforced in
Postgres (trigger + revoked UPDATE/DELETE); this module only inserts and verifies."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AuditEvent:
    actor: str
    action: str
    payload: dict[str, Any]


async def write_audit_event(session: AsyncSession, event: AuditEvent) -> int:
    result = await session.execute(
        text(
            "INSERT INTO audit.audit_log (actor, action, payload) "
            "VALUES (:actor, :action, CAST(:payload AS jsonb)) RETURNING id"
        ),
        {
            "actor": event.actor,
            "action": event.action,
            "payload": json.dumps(event.payload, default=str),
        },
    )
    return int(result.scalar_one())


def compute_row_hash(
    prev_hash: bytes, actor: str, action: str, payload_canonical: str, occurred_at: str
) -> bytes:
    """Mirror of the SQL trigger's hash computation, used by chain verification."""
    material = b"|".join(
        [
            prev_hash,
            actor.encode(),
            action.encode(),
            payload_canonical.encode(),
            occurred_at.encode(),
        ]
    )
    return hashlib.sha256(material).digest()


async def verify_chain(session: AsyncSession, *, limit: int | None = None) -> tuple[bool, int]:
    """Walk the chain in id order; returns (intact, rows_checked)."""
    query = (
        "SELECT id, actor, action, payload::text AS payload, "
        "to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00\"') AS ts, "
        "prev_hash, row_hash FROM audit.audit_log ORDER BY id"
    )
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    rows = (await session.execute(text(query))).mappings().all()
    prev = b"\x00" * 32
    for row in rows:
        if bytes(row["prev_hash"]) != prev:
            return False, len(rows)
        expected = compute_row_hash(prev, row["actor"], row["action"], row["payload"], row["ts"])
        if bytes(row["row_hash"]) != expected:
            return False, len(rows)
        prev = bytes(row["row_hash"])
    return True, len(rows)
