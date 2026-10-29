"""Restore drill against the live fleet: back up, damage every authoritative
store, restore, and prove the damage is undone. A backup that has never been
restored is a hope, not a backup."""

import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from gg_common.audit import verify_chain
from gg_common.backup import create_backup, restore_backup, verify_restored_buckets
from gg_common.objectstore import S3ObjectStore
from gg_common.settings import get_settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

_COMPOSE_FILE = Path(__file__).resolve().parents[2] / "infra" / "compose" / "docker-compose.yml"


async def _thread_exists(marker_owner: str) -> bool:
    """Checked as the app role, not admin: a restore that reloads data but
    breaks the app role's privileges is still a failed restore."""
    engine = create_async_engine(get_settings().postgres.sqlalchemy_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            row = await conn.execute(
                text("SELECT count(*) FROM app.threads WHERE owner = :owner"),
                {"owner": marker_owner},
            )
            return bool(row.scalar_one())
    finally:
        await engine.dispose()


async def _audit_chain_intact() -> tuple[bool, int]:
    """The append-only audit log is a sha256 hash chain. A restore that reloads
    the rows but corrupts their order or content would break the chain, so the
    drill re-verifies it end to end (not just that rows exist)."""
    engine = create_async_engine(get_settings().postgres.sqlalchemy_url, poolclass=NullPool)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            return await verify_chain(session)
    finally:
        await engine.dispose()


async def _app_role_owns_checkpoint_tables() -> bool:
    """The agent checkpointer's tables are created by the app role at runtime
    and carry no GRANTs — access is by ownership. A restore that flattens
    ownership onto the admin role locks the agent out of its own memory."""
    engine = create_async_engine(get_settings().postgres.sqlalchemy_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            row = await conn.execute(text("SELECT count(*) FROM checkpoints.checkpoint_migrations"))
            row.scalar_one()
            return True
    finally:
        await engine.dispose()


async def _execute(statement: str, params: dict[str, Any]) -> None:
    engine = create_async_engine(get_settings().postgres.admin_sqlalchemy_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


def _qdrant_point_count() -> int:
    settings = get_settings().qdrant
    response = httpx.post(
        f"{settings.url}/collections/{settings.collection}/points/count",
        json={"exact": True},
        timeout=30,
    )
    response.raise_for_status()
    return int(response.json()["result"]["count"])


async def test_backup_restore_drill(ingested_corpus, tmp_path):
    settings = get_settings()
    store = S3ObjectStore(settings.objectstore)

    # A marker row proves the postgres restore actually reloads data rather
    # than merely leaving the existing tables alone.
    marker_owner = f"drill-{uuid.uuid4()}"
    await _execute(
        "INSERT INTO app.threads (owner, title) VALUES (:owner, :title)",
        {"owner": marker_owner, "title": "backup drill marker"},
    )

    documents_bucket = settings.objectstore.bucket_documents
    keys = store.list_keys(documents_bucket)
    assert keys, "ingested corpus should have populated the documents bucket"
    probe_key = keys[0]
    original_bytes = store.get(documents_bucket, probe_key)
    points_before = _qdrant_point_count()
    assert points_before > 0

    backup_dir = create_backup(settings, tmp_path, compose_file=_COMPOSE_FILE, store=store)

    # Damage all three stores.
    await _execute(
        "DELETE FROM app.threads WHERE owner = :owner",
        {"owner": marker_owner},
    )
    store.put(documents_bucket, probe_key, b"corrupted by drill")
    deleted = httpx.delete(
        f"{settings.qdrant.url}/collections/{settings.qdrant.collection}", timeout=60
    )
    assert deleted.status_code == 200

    report = restore_backup(settings, backup_dir, compose_file=_COMPOSE_FILE, store=store)

    assert report.postgres_restored and report.qdrant_restored
    assert report.bucket_files_restored > 0
    assert await _thread_exists(marker_owner), "postgres marker row must survive the restore"
    assert await _app_role_owns_checkpoint_tables()
    assert store.get(documents_bucket, probe_key) == original_bytes
    assert _qdrant_point_count() == points_before

    # Full inventory comparison: every object the manifest recorded is back with
    # the recorded bytes — a matching file count alone would not prove that.
    verified = verify_restored_buckets(store, backup_dir)
    assert verified > 0
    # The restored audit log's hash chain still validates end to end.
    chain_ok, checked = await _audit_chain_intact()
    assert chain_ok and checked > 0

    # Leave no drill residue in the shared stack.
    await _execute(
        "DELETE FROM app.threads WHERE owner = :owner",
        {"owner": marker_owner},
    )
