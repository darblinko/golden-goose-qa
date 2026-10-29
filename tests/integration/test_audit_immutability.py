"""Proves the audit log's core guarantees against a live Postgres:

1. The trigger-computed hash chain matches gg_common.audit.compute_row_hash
   byte-for-byte (verify_chain passes).
2. UPDATE and DELETE are rejected for both the runtime role and the admin
   (table owner) — the trigger guards everyone, not just the underprivileged.
3. TRUNCATE is rejected.
"""

import asyncio
import uuid

import pytest
from gg_common.audit import AuditEvent, verify_chain, write_audit_event
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.integration


async def _insert_events(engine, count: int = 3) -> list[int]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = []
    run_id = uuid.uuid4().hex
    async with factory() as session:
        for i in range(count):
            event = AuditEvent(
                actor=f"test-user-{run_id}",
                action="integration.test",
                payload={"sequence": i, "run": run_id, "nested": {"k": "v"}},
            )
            ids.append(await write_audit_event(session, event))
        await session.commit()
    return ids


async def test_chain_verifies_after_inserts(app_engine):
    ids = await _insert_events(app_engine)
    assert len(ids) == 3
    factory = async_sessionmaker(app_engine, expire_on_commit=False)
    async with factory() as session:
        intact, checked = await verify_chain(session)
    assert intact, "hash chain must verify: SQL trigger and compute_row_hash diverged"
    assert checked >= 3


async def test_update_rejected_for_app_role(app_engine):
    await _insert_events(app_engine, count=1)
    async with app_engine.connect() as conn:
        with pytest.raises((DBAPIError, ProgrammingError)):
            await conn.execute(text("UPDATE audit.audit_log SET actor = 'tampered'"))


async def test_delete_rejected_for_app_role(app_engine):
    await _insert_events(app_engine, count=1)
    async with app_engine.connect() as conn:
        with pytest.raises((DBAPIError, ProgrammingError)):
            await conn.execute(text("DELETE FROM audit.audit_log"))


async def test_update_rejected_even_for_admin(admin_engine):
    async with admin_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="append-only"):
            await conn.execute(
                text("UPDATE audit.audit_log SET actor = 'admin-tamper' WHERE id = 1")
            )


async def test_delete_rejected_even_for_admin(admin_engine):
    async with admin_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="append-only"):
            await conn.execute(text("DELETE FROM audit.audit_log WHERE id = 1"))


async def test_truncate_rejected_even_for_admin(admin_engine):
    async with admin_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="append-only"):
            await conn.execute(text("TRUNCATE audit.audit_log"))


async def test_concurrent_writers_keep_chain_contiguous(app_engine):
    """Regression: ids used to be assigned before the chain lock was taken, so
    concurrent inserts could fork the chain (prev_hash pointing past the true
    head). The trigger now assigns ids under the lock."""
    run_id = uuid.uuid4().hex

    async def writer(worker: int) -> None:
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        for i in range(4):
            async with factory() as session:
                await write_audit_event(
                    session,
                    AuditEvent(
                        actor=f"concurrency-{run_id}",
                        action="integration.concurrency",
                        payload={"worker": worker, "sequence": i},
                    ),
                )
                await session.commit()

    await asyncio.gather(*(writer(w) for w in range(8)))

    factory = async_sessionmaker(app_engine, expire_on_commit=False)
    async with factory() as session:
        intact, checked = await verify_chain(session)
    assert intact, "chain must stay contiguous under concurrent writers"
    assert checked >= 32


async def test_prev_hash_links_are_contiguous(app_engine):
    await _insert_events(app_engine, count=2)
    async with app_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT row_hash, prev_hash, "
                    "lag(row_hash) OVER (ORDER BY id) AS expected_prev "
                    "FROM audit.audit_log ORDER BY id"
                )
            )
        ).all()
    assert rows[0].prev_hash == b"\x00" * 32
    for row in rows[1:]:
        assert bytes(row.prev_hash) == bytes(row.expected_prev)
