# ADR 0006: SAQ on Postgres for background jobs (no Redis, no Celery)

Status: accepted (2026-07-17)

## Context
Ingestion is long-running (parse → chunk → embed → index) and must survive
restarts, but the fleet has a hard memory budget and every extra stateful
service is an operational liability locally and a migration burden in cloud.

## Decision
SAQ >= 0.26 with its Postgres queue backend, using the existing Postgres
instance. The worker is `gg_ingestion.worker` (queue + `ingest_corpus` /
`ingest_file` tasks over the shared `IngestionPipeline`), run from the SAQ CLI
(`uv run saq gg_ingestion.worker.settings`) and reusing the API image with a
different command. Job status lands in Postgres where the UI can read it.

## Implementation status (2026-07-18)
- **Queue and worker: implemented.** `saq[postgres]` is a dependency, the
  worker module exists, and the Dockerfile is built so the same image serves
  both the `uvicorn` API (default `CMD`) and the SAQ worker command.
- **Queue tables are owned by SAQ, not by an Alembic migration — by design.**
  SAQ's Postgres backend issues its own `CREATE TABLE IF NOT EXISTS` DDL when a
  queue first connects; there is deliberately no migration-owned queue DDL,
  because coupling our migrations to SAQ's internal schema would fight the
  library across its upgrades. A live database on which the worker has never
  run therefore shows no queue tables — that is expected, not a missing
  baseline.
- **Not yet enabled in compose.** No `worker` service is wired into
  `infra/compose/docker-compose.yml` (the comment there still reads "worker
  joins in Phase 2"). In the current single-container deployment, ingestion
  runs in-process via the CLI/derive path (`gg-ingest derive`, same
  `IngestionPipeline`); the queued out-of-process worker is available but is
  turned on as a deploy-time step with the cloud deployment work
  ([ADR-0020](0020-cloud-skeletons-not-deployment.md)). This does not
  contradict this ADR's storage decision.

## Consequences
- Zero new infrastructure; broker durability = Postgres durability.
- Async-native workers fit the httpx/asyncio codebase (Celery's prefork model
  does not).
- If throughput ever outgrows Postgres queuing, the seam is the job-enqueue
  interface, not scattered call sites.
- Because SAQ self-provisions its schema, standing up the worker in a new
  environment requires no migration step — but any tooling that inventories
  "expected tables" must know the queue tables appear only after the worker's
  first connect.

## Revision history
- 2026-07-18: Reconciled with the shipped code. Clarified that the worker is
  the SAQ-CLI `gg_ingestion.worker` reusing the API image, that SAQ (not
  Alembic) owns the queue DDL and creates it on first connect, and that the
  compose `worker` service is deferred to deploy-time rather than absent by
  oversight. The original text implied a running `worker` container and
  migration-provisioned queue tables; neither the container-in-compose nor a
  migration is present, so the claim was narrowed to what exists.
