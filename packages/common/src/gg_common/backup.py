"""Backup and restore for the authoritative stores.

Authoritative state lives in three places: Postgres (app data, audit log,
registry, chat, agent checkpoints, register warehouse), the object-store
buckets (original documents plus parsed artifacts), and the Qdrant collection
(rebuildable by re-embedding, but snapshotted anyway because re-embedding a
full corpus costs real provider money). The knowledge graph is a rebuildable
projection (ADR 0014) and is deliberately not backed up — restore re-derives
it with `gg-ingest derive`.

pg_dump/pg_restore run inside the postgres container over the local socket
(trust auth), so no password crosses the host boundary. Every dump gets a
sha256 recorded in the manifest and verified before any restore touches data.
"""

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from gg_common.objectstore import ObjectStore, S3ObjectStore
from gg_common.settings import AppSettings, PostgresSettings, QdrantSettings

MANIFEST_NAME = "manifest.json"
POSTGRES_DUMP = "postgres.dump"
QDRANT_SNAPSHOT = "qdrant.snapshot"
BUCKETS_DIR = "buckets"

_QDRANT_TIMEOUT_SECONDS = 300.0


class BackupError(RuntimeError):
    """A backup or restore step failed; state may be partially written."""


@dataclass(frozen=True)
class RestoreReport:
    postgres_restored: bool
    qdrant_restored: bool
    bucket_files_restored: int


def compose_exec_args(compose_file: Path, service: str, command: list[str]) -> list[str]:
    return ["docker", "compose", "-f", str(compose_file), "exec", "-T", service, *command]


def pg_dump_command(settings: PostgresSettings) -> list[str]:
    return ["pg_dump", "-U", settings.admin_user, "-Fc", settings.database]


def pg_restore_command(settings: PostgresSettings) -> list[str]:
    # Ownership must be restored (no --no-owner): tables the app role created
    # at runtime (the agent checkpointer's) carry no explicit GRANTs — access
    # is by ownership alone, so flattening owners onto the admin role would
    # silently lock the app role out.
    return [
        "pg_restore",
        "-U",
        settings.admin_user,
        "-d",
        settings.database,
        "--clean",
        "--if-exists",
    ]


def backup_postgres(settings: PostgresSettings, dest: Path, *, compose_file: Path) -> Path:
    args = compose_exec_args(compose_file, "postgres", pg_dump_command(settings))
    result = subprocess.run(args, capture_output=True)
    if result.returncode != 0:
        raise BackupError(f"pg_dump failed: {result.stderr.decode(errors='replace').strip()}")
    path = dest / POSTGRES_DUMP
    path.write_bytes(result.stdout)
    return path


def restore_postgres(settings: PostgresSettings, dump_path: Path, *, compose_file: Path) -> None:
    args = compose_exec_args(compose_file, "postgres", pg_restore_command(settings))
    result = subprocess.run(args, input=dump_path.read_bytes(), capture_output=True)
    if result.returncode != 0:
        raise BackupError(f"pg_restore failed: {result.stderr.decode(errors='replace').strip()}")


def _qdrant_client(settings: QdrantSettings) -> httpx.Client:
    headers = {}
    if settings.api_key is not None:
        headers["api-key"] = settings.api_key.get_secret_value()
    return httpx.Client(base_url=settings.url, headers=headers, timeout=_QDRANT_TIMEOUT_SECONDS)


def backup_qdrant(settings: QdrantSettings, dest: Path) -> Path:
    with _qdrant_client(settings) as client:
        created = client.post(
            f"/collections/{settings.collection}/snapshots", params={"wait": "true"}
        )
        if created.status_code != 200:
            raise BackupError(f"qdrant snapshot create failed: {created.text}")
        name = created.json()["result"]["name"]
        download = client.get(f"/collections/{settings.collection}/snapshots/{name}")
        if download.status_code != 200:
            raise BackupError(f"qdrant snapshot download failed: {download.status_code}")
        path = dest / QDRANT_SNAPSHOT
        path.write_bytes(download.content)
        # Server-side snapshots accumulate on the qdrant volume; drop after download.
        client.delete(f"/collections/{settings.collection}/snapshots/{name}")
    return path


def restore_qdrant(settings: QdrantSettings, snapshot_path: Path) -> None:
    with _qdrant_client(settings) as client, snapshot_path.open("rb") as fh:
        response = client.post(
            f"/collections/{settings.collection}/snapshots/upload",
            params={"priority": "snapshot", "wait": "true"},
            files={"snapshot": (QDRANT_SNAPSHOT, fh, "application/octet-stream")},
        )
        if response.status_code != 200:
            raise BackupError(f"qdrant snapshot upload failed: {response.text}")


def backup_buckets(store: ObjectStore, buckets: list[str], dest: Path) -> list[dict[str, Any]]:
    """Mirror each bucket into dest/<bucket>/<key>. Returns a per-object
    inventory (bucket, key, bytes, sha256) so the manifest pins every object
    individually — a dropped or altered object is then caught at verify time,
    not just a wrong total count."""
    inventory: list[dict[str, Any]] = []
    for bucket in buckets:
        base = (dest / bucket).resolve()
        for key in store.list_keys(bucket):
            path = (dest / bucket / key).resolve()
            if not path.is_relative_to(base):
                raise BackupError(f"object key escapes backup dir: {bucket}/{key}")
            data = store.get(bucket, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            inventory.append(
                {
                    "bucket": bucket,
                    "key": key,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    return inventory


def restore_buckets(store: ObjectStore, buckets: list[str], source: Path) -> int:
    restored = 0
    for bucket in buckets:
        base = source / bucket
        if not base.is_dir():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            store.put(bucket, str(path.relative_to(base)), path.read_bytes())
            restored += 1
    return restored


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_entry(path: Path) -> dict[str, Any]:
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def write_manifest(backup_dir: Path, components: dict[str, Any]) -> Path:
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "components": components,
    }
    path = backup_dir / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def read_manifest(backup_dir: Path) -> dict[str, Any]:
    path = backup_dir / MANIFEST_NAME
    if not path.is_file():
        raise BackupError(f"no {MANIFEST_NAME} in {backup_dir}; not a backup directory")
    return json.loads(path.read_text())


def _verify_bucket_objects(backup_dir: Path, entry: dict[str, Any]) -> None:
    base = backup_dir / entry["dir"]
    for obj in entry.get("objects", []):
        path = base / obj["bucket"] / obj["key"]
        if not path.is_file():
            raise BackupError(f"backed-up object missing: {obj['bucket']}/{obj['key']}")
        actual = _sha256(path)
        if actual != obj["sha256"]:
            raise BackupError(
                f"object checksum mismatch for {obj['bucket']}/{obj['key']}: "
                f"manifest {obj['sha256']}, file {actual}"
            )


def verify_manifest(backup_dir: Path) -> dict[str, Any]:
    """Check every recorded dump and every backed-up bucket object exists with
    the recorded checksum. Restore refuses to run against a backup that fails
    this — a truncated, dropped, or tampered file must never be loaded into the
    datastores."""
    manifest = read_manifest(backup_dir)
    for component, entry in manifest["components"].items():
        if "file" in entry:
            path = backup_dir / entry["file"]
            if not path.is_file():
                raise BackupError(f"{component} dump missing: {entry['file']}")
            actual = _sha256(path)
            if actual != entry["sha256"]:
                raise BackupError(
                    f"{component} checksum mismatch: manifest {entry['sha256']}, file {actual}"
                )
        elif "objects" in entry:
            _verify_bucket_objects(backup_dir, entry)
    return manifest


def verify_restored_buckets(store: ObjectStore, backup_dir: Path) -> int:
    """Confirm the live store, after a restore, holds every object the manifest
    recorded, byte-for-byte. Returns the count verified; raises BackupError on
    the first missing or mismatched object. This closes the restore drill: a
    matching file count is not proof the right bytes came back."""
    manifest = read_manifest(backup_dir)
    entry = manifest["components"].get("buckets", {})
    verified = 0
    for obj in entry.get("objects", []):
        if not store.exists(obj["bucket"], obj["key"]):
            raise BackupError(f"restored object missing: {obj['bucket']}/{obj['key']}")
        actual = hashlib.sha256(store.get(obj["bucket"], obj["key"])).hexdigest()
        if actual != obj["sha256"]:
            raise BackupError(
                f"restored object mismatch for {obj['bucket']}/{obj['key']}: "
                f"manifest {obj['sha256']}, store {actual}"
            )
        verified += 1
    return verified


def create_backup(
    settings: AppSettings, dest_root: Path, *, compose_file: Path, store: ObjectStore | None = None
) -> Path:
    """Full backup into a new timestamped directory under dest_root."""
    backup_dir = dest_root / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir.mkdir(parents=True, exist_ok=False)
    buckets = [settings.objectstore.bucket_documents, settings.objectstore.bucket_artifacts]
    resolved_store = store if store is not None else S3ObjectStore(settings.objectstore)

    pg_path = backup_postgres(settings.postgres, backup_dir, compose_file=compose_file)
    qdrant_path = backup_qdrant(settings.qdrant, backup_dir)
    inventory = backup_buckets(resolved_store, buckets, backup_dir / BUCKETS_DIR)

    write_manifest(
        backup_dir,
        {
            "postgres": _file_entry(pg_path) | {"database": settings.postgres.database},
            "qdrant": _file_entry(qdrant_path) | {"collection": settings.qdrant.collection},
            "buckets": {
                "dir": BUCKETS_DIR,
                "names": buckets,
                "files": len(inventory),
                "objects": inventory,
            },
        },
    )
    return backup_dir


def restore_backup(
    settings: AppSettings, backup_dir: Path, *, compose_file: Path, store: ObjectStore | None = None
) -> RestoreReport:
    """Restore all components from a verified backup. The knowledge graph is
    not part of the backup; re-derive it afterwards with `gg-ingest derive`
    (see docs/runbooks/backup-restore.md)."""
    manifest = verify_manifest(backup_dir)
    components = manifest["components"]
    resolved_store = store if store is not None else S3ObjectStore(settings.objectstore)

    restore_postgres(
        settings.postgres, backup_dir / components["postgres"]["file"], compose_file=compose_file
    )
    restore_qdrant(settings.qdrant, backup_dir / components["qdrant"]["file"])
    bucket_names = components["buckets"]["names"]
    if isinstance(resolved_store, S3ObjectStore):
        for bucket in bucket_names:
            resolved_store.ensure_bucket(bucket)
    restored = restore_buckets(
        resolved_store, bucket_names, backup_dir / components["buckets"]["dir"]
    )
    return RestoreReport(
        postgres_restored=True, qdrant_restored=True, bucket_files_restored=restored
    )
