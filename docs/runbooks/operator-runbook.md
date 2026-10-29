# Operator Runbook

Day-to-day operation of a Golden Goose deployment. Backup and restore have
their own runbook: `docs/runbooks/backup-restore.md`.

## Fleet

All commands run from the repo root.

```bash
# start the core fleet (postgres, qdrant, seaweedfs, neo4j)
docker compose -f infra/compose/docker-compose.yml --profile core up -d

# add Phoenix tracing (optional; set OTEL_EXPORTER_OTLP_ENDPOINT in .env)
docker compose -f infra/compose/docker-compose.yml --profile obs up -d

# stop everything, keep data volumes
docker compose -f infra/compose/docker-compose.yml --profile core down

# stop and DESTROY data volumes (dev reset only — take a backup first)
docker compose -f infra/compose/docker-compose.yml --profile core down -v
```

Apply migrations after every deploy and before first use:

```bash
uv run alembic -c infra/migrations/alembic.ini upgrade head
uv run gg-ingest graph-migrate
```

## Services

```bash
uv run uvicorn goldengoose_api.main:app --port 8000   # API
cd apps/web && npm run dev                            # web UI on :3000
```

Health: `GET /health` (process up), `GET /ready` (fleet reachable). The web
UI has no state of its own.

## Ingestion

```bash
uv run gg-ingest run --corpus <dir>   # ingest; unchanged files skip by content hash
uv run gg-ingest status               # registry counts per document state
uv run gg-ingest derive               # rebuild knowledge graph + register warehouse
uv run gg-ingest sync                 # re-check source dirs for changes
```

`derive` is idempotent and safe to re-run at any time; it reprojects from
parsed artifacts (ADR 0014). Run it after any restore and after bulk
ingestion.

## Evaluation

```bash
# full gated battery: retrieval, answers, routing, reranker noise
uv run gg-eval battery --qa data/synthetic/qa/golden_qa.json \
  --history eval-trends/history.jsonl --dashboard eval-trends/dashboard.html

# quick smoke subset
uv run gg-eval battery --qa data/synthetic/qa/smoke_qa.json --smoke
```

Nonzero exit means a gate failed; the output names the gate, value, and
bound. Gates and their calibration are in ADR 0019. The nightly workflow
(`.github/workflows/nightly-eval.yml`) runs the full battery against a
freshly generated corpus and appends to the trend dashboard.

## Load sanity

Before a release, confirm the memory budget holds under concurrent chat and
ingestion:

```bash
uv run python scripts/load_sanity.py
```

Starts its own API on :8600, runs 10 concurrent sessions x 2 turns while
`gg-ingest derive` runs, samples container memory, and fails on any turn
error or a container above 90% of its compose limit.

## Dependency audits

```bash
uv run python scripts/license_audit.py                      # license policy
uv export --locked --no-emit-workspace --format requirements-txt \
  -o /tmp/requirements.txt && uvx pip-audit -r /tmp/requirements.txt
cd apps/web && npm audit --audit-level=high                 # web dependencies
```

All three also run in the CI `audit` job.

## Common failures

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `/ready` red, API up | A fleet container is down or still starting | `docker compose ... ps`; check the failing container's logs |
| Answers cite nothing / verifier says ungrounded on known content | Corpus not ingested, or derive not run after restore | `gg-ingest status`; re-run `gg-ingest run` / `derive` |
| Count/trace questions give prose instead of numbers | Registers or graph empty | `uv run gg-ingest derive` |
| Battery routing gate fails after a toolselect change | Regex layer regressed | `uv run pytest packages/agents/tests/test_toolselect.py`; misroutes are listed in battery output |
| Neo4j container OOM-killed during derive | Graph memory limit too low for corpus size | Raise the neo4j limit in `infra/compose/docker-compose.yml`; re-check with `scripts/load_sanity.py` |
| Provider errors in answers with keys configured | Key invalid/expired or provider outage | Check `.env` keys; unset to fall back to deterministic fakes while diagnosing |
| Restore completed but graph queries empty | Derive step skipped | `gg-ingest graph-migrate && gg-ingest derive` (ADR 0018) |
