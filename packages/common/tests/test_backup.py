"""Backup manifest, checksum verification, and bucket mirroring (offline)."""

import hashlib

import pytest
from gg_common.backup import (
    BackupError,
    backup_buckets,
    compose_exec_args,
    pg_dump_command,
    pg_restore_command,
    read_manifest,
    restore_buckets,
    verify_manifest,
    verify_restored_buckets,
    write_manifest,
)
from gg_common.objectstore import LocalObjectStore
from gg_common.settings import PostgresSettings


def test_compose_exec_args_shape(tmp_path):
    compose = tmp_path / "docker-compose.yml"
    args = compose_exec_args(compose, "postgres", ["pg_dump", "-Fc", "db"])
    assert args[:2] == ["docker", "compose"]
    assert "-T" in args  # no TTY: output must be the dump bytes, nothing else
    assert args[-3:] == ["pg_dump", "-Fc", "db"]


def test_pg_commands_use_admin_user_and_database():
    settings = PostgresSettings(admin_user="gg_admin", database="goldengoose")
    dump = pg_dump_command(settings)
    assert "gg_admin" in dump and "goldengoose" in dump and "-Fc" in dump
    restore = pg_restore_command(settings)
    assert "--clean" in restore and "--if-exists" in restore
    # Runtime-created tables (agent checkpointer) have no GRANTs; access is by
    # ownership, so the restore must reinstate original owners.
    assert "--no-owner" not in restore


def test_manifest_roundtrip_and_verify(tmp_path):
    dump = tmp_path / "postgres.dump"
    dump.write_bytes(b"dump-bytes")
    write_manifest(
        tmp_path,
        {
            "postgres": {
                "file": "postgres.dump",
                "bytes": 10,
                "sha256": hashlib.sha256(b"dump-bytes").hexdigest(),
            }
        },
    )
    manifest = verify_manifest(tmp_path)
    assert manifest["components"]["postgres"]["file"] == "postgres.dump"
    assert "created_at" in manifest


def test_verify_rejects_checksum_mismatch(tmp_path):
    dump = tmp_path / "postgres.dump"
    dump.write_bytes(b"original")
    write_manifest(
        tmp_path,
        {
            "postgres": {
                "file": "postgres.dump",
                "bytes": 8,
                "sha256": hashlib.sha256(b"original").hexdigest(),
            }
        },
    )
    dump.write_bytes(b"tampered")
    with pytest.raises(BackupError, match="checksum mismatch"):
        verify_manifest(tmp_path)


def test_verify_rejects_missing_dump(tmp_path):
    write_manifest(tmp_path, {"postgres": {"file": "gone.dump", "bytes": 1, "sha256": "x"}})
    with pytest.raises(BackupError, match="dump missing"):
        verify_manifest(tmp_path)


def test_read_manifest_requires_backup_directory(tmp_path):
    with pytest.raises(BackupError, match="not a backup directory"):
        read_manifest(tmp_path)


def test_bucket_backup_restore_roundtrip(tmp_path):
    source_store = LocalObjectStore(tmp_path / "source")
    source_store.put("gg-documents", "sops/sop-001.md", b"sop body")
    source_store.put("gg-documents", "nested/deep/file.pdf", b"pdf bytes")
    source_store.put("gg-artifacts", "parsed/sop-001.json", b"{}")

    backup_dir = tmp_path / "backup" / "buckets"
    inventory = backup_buckets(source_store, ["gg-documents", "gg-artifacts"], backup_dir)
    assert len(inventory) == 3
    # Every object is pinned by its own sha256, not just a total count.
    pdf = next(o for o in inventory if o["key"] == "nested/deep/file.pdf")
    assert pdf["sha256"] == hashlib.sha256(b"pdf bytes").hexdigest()
    assert pdf["bytes"] == len(b"pdf bytes")

    target_store = LocalObjectStore(tmp_path / "target")
    restored = restore_buckets(target_store, ["gg-documents", "gg-artifacts"], backup_dir)
    assert restored == 3
    assert target_store.get("gg-documents", "nested/deep/file.pdf") == b"pdf bytes"
    assert target_store.get("gg-artifacts", "parsed/sop-001.json") == b"{}"


def test_restore_buckets_tolerates_absent_bucket_dir(tmp_path):
    store = LocalObjectStore(tmp_path / "target")
    assert restore_buckets(store, ["gg-documents"], tmp_path / "empty") == 0


def _backup_with_one_object(tmp_path):
    source = LocalObjectStore(tmp_path / "source")
    source.put("gg-documents", "SOP-004/hash/file.pdf", b"controlled bytes")
    inventory = backup_buckets(source, ["gg-documents"], tmp_path / "buckets")
    write_manifest(
        tmp_path,
        {
            "buckets": {
                "dir": "buckets",
                "names": ["gg-documents"],
                "files": 1,
                "objects": inventory,
            }
        },
    )
    return inventory


def test_verify_manifest_rejects_altered_bucket_object(tmp_path):
    _backup_with_one_object(tmp_path)
    # Tamper with the mirrored object; its manifest sha256 no longer matches.
    (tmp_path / "buckets" / "gg-documents" / "SOP-004" / "hash" / "file.pdf").write_bytes(
        b"tampered"
    )
    with pytest.raises(BackupError, match="object checksum mismatch"):
        verify_manifest(tmp_path)


def test_verify_manifest_rejects_missing_bucket_object(tmp_path):
    _backup_with_one_object(tmp_path)
    (tmp_path / "buckets" / "gg-documents" / "SOP-004" / "hash" / "file.pdf").unlink()
    with pytest.raises(BackupError, match="object missing"):
        verify_manifest(tmp_path)


def test_verify_restored_buckets_confirms_bytes(tmp_path):
    _backup_with_one_object(tmp_path)
    store = LocalObjectStore(tmp_path / "restored")
    store.put("gg-documents", "SOP-004/hash/file.pdf", b"controlled bytes")
    assert verify_restored_buckets(store, tmp_path) == 1


def test_verify_restored_buckets_detects_wrong_bytes(tmp_path):
    _backup_with_one_object(tmp_path)
    store = LocalObjectStore(tmp_path / "restored")
    store.put("gg-documents", "SOP-004/hash/file.pdf", b"different bytes")
    with pytest.raises(BackupError, match="restored object mismatch"):
        verify_restored_buckets(store, tmp_path)


def test_verify_restored_buckets_detects_missing(tmp_path):
    _backup_with_one_object(tmp_path)
    store = LocalObjectStore(tmp_path / "restored")  # nothing restored
    with pytest.raises(BackupError, match="restored object missing"):
        verify_restored_buckets(store, tmp_path)
