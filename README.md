# Golden Goose

Agentic retrieval chat platform for live regulatory audit support at a Class 3 medical device
company. LangGraph agent over hybrid RAG (Qdrant dense+sparse), a schema-first knowledge graph
(Neo4j), a structured warehouse (Postgres), and external regulatory tools (openFDA, eCFR,
ClinicalTrials.gov, PubMed, web search).

Read-only over quality records. Every answer cites doc ID, revision, and page. Every turn is
written to an append-only, hash-chained audit log.

## Documentation

- `docs/architecture/system-architecture.md` — master architecture
- `docs/planning/implementation-plan.md` — phased plan with acceptance criteria
- `docs/research/` — research reports 01-03 underpinning the design
- `docs/adr/` — architecture decision records
- `docs/validation/` — intended use statement and requirements traceability
- `docs/runbooks/` — operator runbook, backup and restore, cloud deployment

## Quick start

Requirements: Docker, uv (>=0.8), Node 20+.

```bash
cp .env.example .env          # provider API keys; without them deterministic fakes are used
uv sync
docker compose -f infra/compose/docker-compose.yml --profile core up -d
uv run alembic -c infra/migrations/alembic.ini upgrade head
uv run pytest
```

Generate the synthetic QMS corpus, ingest it, and check the retrieval gate:

```bash
uv run synthdata generate --out /tmp/gg-corpus
uv run gg-ingest run --corpus /tmp/gg-corpus/corpus
uv run gg-ingest graph-migrate    # Neo4j schema constraints
uv run gg-ingest derive           # knowledge graph + register warehouse from parsed artifacts
uv run gg-eval retrieval --qa /tmp/gg-corpus/qa/golden_qa.json --smoke   # recall@10 gate 0.8
```

Operations and quality gates:

```bash
uv run gg-eval battery --qa /tmp/gg-corpus/qa/golden_qa.json   # gated eval battery
uv run gg-backup create --dest backups                         # backup authoritative stores
uv run python scripts/load_sanity.py                           # concurrent chat + derive load check
uv run python scripts/license_audit.py                         # dependency license policy
```

The battery gates retrieval recall, grounded answer rate, sentence support,
deterministic routing accuracy, and reranker noise robustness (ADR 0019); a
nightly workflow reruns it from a fresh corpus and renders a trend dashboard.
See `docs/runbooks/operator-runbook.md` for the full operating procedures.

Run the API and the web UI:

```bash
uv run uvicorn goldengoose_api.main:app --port 8000
cd apps/web && npm install && npm run dev     # http://localhost:3000
```

Sign in with any email (dev tokens are minted locally in `local`/`ci`
environments only), start a thread, and ask e.g. "What does the CAPA
procedure require before a CAPA can be closed?" — the answer streams with
agent steps, citations open in the side panel, and the turn lands in the
hash-chained audit log.

Count and trace questions ("How many complaints were received in 2024?",
"Which verification reports cover REQ-001?") route deterministically to the
register warehouse and the knowledge graph, so they answer with exact
numbers and walked edges even when no provider keys are configured.

## Layout

```
apps/api          FastAPI + LangGraph service (uvicorn / saq worker entrypoints)
apps/web          Next.js frontend
packages/common   settings, models, provider adapters, object store, telemetry
packages/ingestion  registry, parser router, chunkers, extractors, pipeline tasks
packages/retrieval  hybrid search, fusion, rerank, graph traversal, SQL tools
packages/agents   LangGraph graphs, nodes, prompts, tool registry
packages/synthdata  synthetic QMS corpus generator + golden QA sets
infra/compose     docker compose (profiles: core, obs, ci)
infra/migrations  Alembic (Postgres) + versioned Cypher (Neo4j)
infra/terraform   AWS / Azure skeletons
```
