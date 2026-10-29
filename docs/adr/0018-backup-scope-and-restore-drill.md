# ADR 0018: Backup scope — authoritative stores only, restore proven by drill

Status: accepted (2026-07-18)

## Context
The fleet has four datastores but not four sources of truth. Postgres holds
chat history, the append-only audit log, the ingestion registry, and the
register warehouse; the object store holds source documents and parsed
artifacts; Qdrant holds embeddings; Neo4j holds the knowledge graph. ADR
0014 established that the graph and the registers are rebuildable
projections of parsed artifacts. Backing up everything equally would spend
disk and restore time on data that `gg-ingest derive` regenerates in
seconds, while under-specifying restore order for the data that cannot be
regenerated at all.

## Decision
- `gg-backup create` dumps only the authoritative stores: `pg_dump -Fc`
  (run inside the postgres container, so no host password path), a full
  mirror of both object-store buckets, and a Qdrant collection snapshot —
  the vectors are rebuildable but re-embedding costs real provider money,
  so they are treated as semi-authoritative.
- Neo4j is deliberately not backed up. Restore is: load the Postgres dump,
  restore the buckets and the Qdrant snapshot, then run
  `gg-ingest graph-migrate && gg-ingest derive` to reproject the graph and
  registers.
- Every artifact in a backup set — the Postgres dump, the Qdrant snapshot, and
  each individual object in both buckets — is sha256-checksummed into
  `manifest.json`; restore verifies every checksum before touching any
  datastore, so a dropped or altered object fails the restore, not just a
  truncated dump.
- The restore path is verified by an integration test that creates a backup,
  damages all three stores, restores, and asserts the chat/audit/registry
  contents came back — a restore drill in CI, not a script that is trusted
  until the day it is needed. The drill also compares the full bucket inventory
  byte-for-byte against the manifest and re-runs the audit hash-chain check
  (`verify_chain`), so "the files are back" is proven, not assumed.

## Consequences
- Backup sets are small and the restore procedure has one documented order
  (runbook `docs/runbooks/backup-restore.md`).
- Restoring requires running the derive step; an operator who skips it gets
  an empty graph. The runbook and the restore command's output both say so.
- `pg_dump` preserves ownership; the drill exposed that restoring into a
  container with a different superuser name fails unless the dump is loaded
  as the same role — the compose environment pins the role name for this
  reason.
