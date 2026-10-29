"""Backup CLI.

    gg-backup create [--dest backups] [--compose-file infra/compose/docker-compose.yml]
    gg-backup restore --backup-dir backups/<timestamp> [--compose-file ...]

Restore loads Postgres, the Qdrant collection, and the object-store buckets.
The knowledge graph is a rebuildable projection: run `gg-ingest derive` after
a restore. Full procedure: docs/runbooks/backup-restore.md.
"""

import argparse
import sys
from pathlib import Path

from gg_common.backup import BackupError, create_backup, read_manifest, restore_backup
from gg_common.logging import configure_logging
from gg_common.settings import get_settings

_DEFAULT_COMPOSE_FILE = Path("infra/compose/docker-compose.yml")


def _create(dest: Path, compose_file: Path) -> int:
    settings = get_settings()
    backup_dir = create_backup(settings, dest, compose_file=compose_file)
    manifest = read_manifest(backup_dir)
    print(f"backup written to {backup_dir}")
    for component, entry in manifest["components"].items():
        if "file" in entry:
            print(f"  {component}: {entry['file']} ({entry['bytes']} bytes)")
        else:
            print(f"  {component}: {entry['files']} files in {entry['dir']}/")
    return 0


def _restore(backup_dir: Path, compose_file: Path) -> int:
    settings = get_settings()
    report = restore_backup(settings, backup_dir, compose_file=compose_file)
    print(f"restored from {backup_dir}")
    print(f"  postgres: restored ({settings.postgres.database})")
    print(f"  qdrant: restored ({settings.qdrant.collection})")
    print(f"  buckets: {report.bucket_files_restored} files")
    print("graph is not part of the backup: run `gg-ingest derive` to rebuild it")
    return 0


def main() -> int:
    settings = get_settings()
    configure_logging(settings)
    parser = argparse.ArgumentParser(prog="gg-backup")
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=_DEFAULT_COMPOSE_FILE,
        help="compose file that runs the postgres service",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="back up postgres, qdrant, and buckets")
    create.add_argument("--dest", type=Path, default=Path("backups"))

    restore = sub.add_parser("restore", help="restore a backup directory")
    restore.add_argument("--backup-dir", type=Path, required=True)

    args = parser.parse_args()
    if not args.compose_file.is_file():
        print(f"compose file not found: {args.compose_file}", file=sys.stderr)
        return 2
    try:
        if args.command == "create":
            return _create(args.dest, args.compose_file)
        return _restore(args.backup_dir, args.compose_file)
    except BackupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
