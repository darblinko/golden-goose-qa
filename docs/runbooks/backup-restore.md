# Backup and Restore Runbook

## What is authoritative, what is rebuilt

| Store | Contents | Backup treatment |
| --- | --- | --- |
| Postgres (`goldengoose`) | Chat threads/messages, audit log, ingestion registry, parent chunks, register warehouse, agent checkpoints, migration state | `pg_dump -Fc`, restored with `pg_restore --clean` |
| Object store (`gg-documents`, `gg-artifacts`) | Original source documents; parsed artifacts | Full bucket mirror into the backup directory |
| Qdrant (`gg_chunks`) | Child-chunk vectors + payloads | Collection snapshot. Rebuildable by re-ingesting, but re-embedding a corpus costs real provider money, so it is snapshotted anyway |
| Neo4j | Knowledge graph | **Not backed up.** It is a rebuildable projection (ADR 0014): restore re-derives it with `gg-ingest derive` |
| Registers schema | Register warehouse rows | Included in the Postgres dump; also rebuildable via `gg-ingest derive` |

Every dump **and every backed-up bucket object** gets a sha256 in
`manifest.json`; restore verifies all of them before touching any datastore and
refuses to load a truncated, dropped, or altered file.

## Taking a backup

From the repo root, with the core compose profile running:

```bash
uv run gg-backup create --dest backups
```

This writes `backups/<UTC timestamp>/` containing `postgres.dump`,
`qdrant.snapshot`, `buckets/`, and `manifest.json`. `pg_dump` runs inside the
postgres container over the local socket; no database password is required on
the host.

Schedule: nightly before the eval run, and always immediately before a
migration or a bulk re-ingestion. The backup directory is local disk —
copy it to storage that does not share fate with the docker volumes
(another machine, object storage, offline media). A backup on the same disk
as the database protects against operator error, not hardware loss.

## Restoring

1. Stop the application so nothing writes during the restore (datastores stay up):

   ```bash
   docker compose -f infra/compose/docker-compose.yml stop api web
   ```

   Use `stop api web`, not `--profile app down`: `down` operates on the whole
   project and would also remove the postgres/qdrant containers the restore
   loads into. Stopping only the app tier keeps the datastores running.

2. Restore the verified backup:

   ```bash
   uv run gg-backup restore --backup-dir backups/<timestamp>
   ```

   This reloads Postgres (`pg_restore --clean --if-exists`, so the database is
   replaced, not merged), recovers the Qdrant collection from its snapshot
   (recreating it if it was deleted), and re-uploads both buckets.

3. Rebuild the knowledge graph projection:

   ```bash
   uv run gg-ingest graph-migrate
   uv run gg-ingest derive
   ```

4. Restart and verify:

   ```bash
   docker compose -f infra/compose/docker-compose.yml start api web
   uv run gg-ingest status        # registry counts look right
   curl -s localhost:8000/health  # api healthy
   ```

   Then ask one grounded question through the UI and confirm citations render.

## Prerequisites and caveats

- Database **roles** (`gg_admin`, `gg_app`, and the restricted-read roles) are
  cluster-level and are not in the dump. On a brand-new Postgres volume, start
  the compose service (which creates `gg_admin`) and apply migrations once
  (`uv run alembic upgrade head`) before restoring, so all roles referenced by
  the dump's GRANTs exist.
- Restore replaces the whole database. Anything written after the backup
  timestamp is gone — take a fresh backup before restoring if the current
  state might still be needed.
- The Qdrant snapshot is restored into the collection name recorded in the
  manifest. A renamed collection needs a re-ingest, not a restore.

## Drill

The restore path is exercised by `tests/integration/test_backup_restore.py`:
it backs up the live dev fleet, deletes a Postgres row, corrupts a document
object, drops the Qdrant collection entirely, restores, and asserts all three
are back. It then re-verifies the full bucket inventory byte-for-byte against
the manifest (`verify_restored_buckets`) and re-runs the audit hash-chain check
(`verify_chain`) to prove the append-only log survived the round trip. Run it
whenever the backup code or the datastore versions change:

```bash
uv run pytest -q -m integration tests/integration/test_backup_restore.py
```
