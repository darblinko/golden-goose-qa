# Golden Goose — Phased Implementation Plan

Version 0.1 — 2026-07-17. Companion to `docs/architecture/system-architecture.md`.

Ground rules:
- Git from the first file; conventional commits; PRs to main; CI is the definition of "done."
- Status claims come only from executable checks — integration tests, eval gates, smoke probes.
- No failure converted to a plausible default; errors are counted, surfaced, and queryable.
- uv lockfile + pinned images from day one; effective config logged at startup; single source of
  config truth (pydantic-settings), no literal defaults shadowing it.

Each phase ends with acceptance criteria that are commands, not opinions.

---

## Phase 0 — Foundation (repo, compose, CI)

**Deliverables**
- uv workspace monorepo per architecture §5; Python 3.13 pin; ruff + mypy + pytest wired.
- `infra/compose`: pinned images for qdrant / neo4j / postgres(pg18+pgvector) / seaweedfs with
  memory limits, named volumes, internal network, healthchecks; profiles `core`, `obs` (phoenix),
  `ci` (ephemeral, tmpfs).
- One app image (multi-stage uv build, `UV_COMPILE_BYTECODE=1`), api + worker entrypoints.
- Alembic baseline: `app`, `registers`, `checkpoints`, `audit` schemas; audit table with
  REVOKE + trigger no-update/no-delete + sha256 hash chain; SAQ queue tables; sandboxed
  `sql_tool_ro` role.
- `.env.example` complete; secrets only via env; GitHub Actions: lint, type, unit, compose-up
  integration smoke.
- ADR-0001..000N recording the stack verdicts (SeaweedFS, SAQ, Better Auth-style OIDC, Phoenix,
  Neo4j-day-one) so future sessions don't relitigate.

**Accept:** `docker compose --profile ci up` green healthchecks; `uv run pytest` green in CI;
audit-table immutability proven by a test that attempts UPDATE/DELETE and asserts failure.

## Phase 1 — Synthetic Class 3 QMS corpus + golden QA set

**Deliverables** (`packages/synthdata`)
- Generator for a coherent fictional Class 3 device company ("Halvern Medical, Inc.", HALVERN
  implantable infusion pump, models MP-100 and MP-200): numbering scheme, org, product family,
  assembly tree.
- Document families v1: quality manual, 20–30 SOPs/WIs (Word/PDF), design plan, design inputs,
  design outputs, trace matrix (Excel), DFMEA + PFMEA (Excel, realistic merged-cell templates),
  risk management plan/analysis/report, 30–50 NCRs, 20–30 CAPAs, 50–100 complaints + a handful of
  MDRs, DHR travelers (some rendered to scanned-style images for OCR testing), training matrix,
  supplier files. All cross-referenced with valid IDs; revision histories; a QSR-era subset and a
  post-QMSR subset.
- **Seeded defects** (the eval backbone): broken trace links, an AP mismatch, an overdue
  effectiveness check, a complaint never evaluated against the risk file, a stale SOP reference.
- Golden QA set v1: 150+ questions with labeled evidence chunk/doc IDs, mapped to the 10 audit
  query patterns; 30-question PR smoke subset.

**Accept:** `uv run synthdata generate` produces the corpus deterministically from a seed;
generator unit-tested; QA set schema-validated; corpus documents open correctly (spot-check
script asserts parseability of every emitted file).

## Phase 2 — Milestone 1: end-to-end thin slice

Narrow doc coverage (SOP narrative, CAPA form, NCR form, trace matrix, DFMEA), every layer real.

**Deliverables**
- Ingestion: registry + content-hash idempotency; parser router with Docling (narrative) and
  openpyxl matrix path (trace + DFMEA with forward-fill/two-row headers); structural parent-child
  chunking + contextual prepend; voyage-4-large int8 + Qdrant BM25 sparse; UUIDv5 points,
  delete-before-upsert; per-doc metrics.json with hard QA gates; SAQ pipeline with staged
  artifacts in SeaweedFS.
- Retrieval: Qdrant Query API hybrid (RRF, server-injected status/ACL filters), parent expansion,
  voyage rerank-2.5; `/health/retrieval` stage-by-stage probe.
- Agent v1: LangGraph StateGraph — route → retrieve (vector only) → grade (≤2 rewrites) →
  cite-mandatory generate → entailment verify → SSE stream; PostgresSaver; audit-log writes on
  every turn.
- Web v1: Next.js chat with streaming, agent-step trace, citation side panel opening PDF at
  page/bbox, login (Better Auth, local users), thread history.
- Eval harness v1: ranx retrieval metrics + DeepEval smoke gate in CI against the golden subset.

**Accept:** fresh clone → `docker compose up` → ingest synthetic corpus → ask "What is the
current revision of the incoming-inspection SOP and who approved it?" and a CAPA-thread question
→ answers stream with correct citations; retrieval recall@10 ≥ 0.8 on the smoke set; CI runs the
smoke eval as a gate; audit log rows present and hash-chained for every turn.

## Phase 3 — Knowledge graph + structured warehouse

**Deliverables**
- Neo4j schema v1 (architecture §8) with versioned Cypher migrations; deterministic edge
  extraction from trace matrices, form fields, revision tables, References sections, inline regex
  (ID bank + validation against registry); per-edge provenance + confidence; DocumentRevision
  temporal model.
- FMEA subgraph per the FMEA labels in architecture §8; AIAG-VDA Action Priority table with tests
  (`gg_common.actionpriority`) and methodology profiles; AP recompute + mismatch flag.
- `registers` warehouse: NCR/CAPA/complaint/deviation/training/FMEA tables + curated read-only
  views; text-to-SQL tool under `sql_tool_ro` with result citation (table/view + filter echo).
- Graph traversal tools (pre-canned Cypher): revision_history, capa_thread, trace_requirement,
  impacted_documents, training_as_of; agent router extended to graph/SQL families; graph+vector
  join via doc_id-filtered fetch → unified rerank.
- DuckDB ad-hoc file tool.

**Accept:** thread-walk question ("walk me through CAPA-2025-014 end to end") answered from graph
with citations; count question ("how many open NCRs > 90 days") answered via SQL exactly matching
warehouse ground truth; seeded broken-trace defect discoverable by a trace-walk query; eval gate
extended with graph/SQL pattern questions and green.

## Phase 4 — Document breadth + OCR path

**Deliverables**
- Remaining families: risk file narratives, complaints/MDR (incl. eMDR XML), DHR/batch records,
  supplier packages, audit reports, management review, clinical (protocol/CER), PFMEA + control
  plan linking (`REALIZED_IN`/`CONTROLLED_BY`).
- Scanned path: page-level text-layer probe; hosted VLM OCR over pages with bounded concurrency
  and per-page retry (each page sent with its detected image MIME type); a hybrid PDF's image-only
  pages recovered via per-page OCR fallback; enforced per-page confidence gates; scanned DHR
  travelers from synthdata proven. (A provider-side batch/warm-up request API with progressive
  batch splitting is intentionally out of scope: it is a hosted-only optimization that cannot be
  contract-tested without a live key, and the bounded-concurrency + per-page-retry path is safe.)
- QSR↔ISO 13485 synonym layer at query time; as-of-date filters end-to-end.
- Connector interface (`SourceConnector`) + filesystem/watch-folder implementation; SharePoint
  connector if credentials available, else contract-tested stub.

**Accept:** full synthetic corpus (all families) ingests with QA-gate report showing zero silent
failures; as-of question ("which rev of WI-MFG-014 was effective on the DHR date, and was the
operator trained on it?") answered correctly; OCR confidence gate demonstrably blocks a degraded
scan; nightly full eval green.

## Phase 5 — External tools + audit workflows

**Deliverables**
- Tool families: openFDA (MAUDE, recalls, 510(k)/PMA, GUDID, warning letters), eCFR + FDA
  guidance fetch, ClinicalTrials.gov, PubMed, web search (provider-abstracted); per-tool result
  provenance typed as external (never confused with QMS citations); rate limiting + caching.
- Internal-API connector framework (read-only, config-registered, credential-scoped).
- Audit workflows: gap-detection reports from seeded-defect patterns (readiness-style
  deterministic gates + advisory LLM notes); reconciliation diffs (complaint log vs MDRs filed;
  ECO log vs submissions); currency sweeps (overdue reviews, aging CAPAs) as saved queries;
  audit-prep collections in UI.
  - *Deviation:* the synthetic corpus contains no ECO/change-order records, so the planned
    "ECO log vs submissions" diff has nothing to reconcile. Substituted a training-vs-revision
    reconciliation (graph: TRAINED_ON revision vs current Document revision), which exercises
    the same cross-source diff shape against data the corpus actually has. Revisit if ECO
    records are added to the world model.
- Roles/ACL enforcement end-to-end (admin / qa_user / auditor_readonly) incl. Qdrant filter
  injection tests and Postgres RLS.

**Accept:** "How does our complaint rate for this device class compare to MAUDE?" answers with
clearly separated internal vs external citations; reconciliation report reproduces every seeded
defect; ACL test proves a restricted user cannot retrieve a restricted document through any tool
path.

## Phase 6 — Hardening + validation readiness

**Deliverables**
- Observability: Phoenix + OTel traces across api/worker; cost telemetry per pipeline stage and
  per conversation; backup/restore scripts (pg_dump, Qdrant snapshots to SeaweedFS, neo4j dump)
  with a tested restore runbook.
- Load sanity: 10 concurrent chat sessions during active ingestion on the 10 GB fleet.
- Docs: intended-use statement, requirements-to-test traceability for the app itself, operator
  runbook — the validation-ready package.
- Full eval battery: RAGAS dashboards, NoiseSensitivity, citation-entailment gate ≥ target,
  per-node evals; dependency + license audit in CI.

**Accept:** restore-from-backup drill passes; load test passes within memory limits; nightly eval
trend dashboard exists; docs reviewed.

## Phase 7 — Cloud extensibility (optional, when needed)

Terraform skeletons for AWS (ECS Fargate, RDS, S3, Cognito) and Azure (Container Apps, Azure
PG, Blob, Entra) exercising the four adapter seams; CI job that builds/pushes images; deployment
runbook. **Accept:** dev deploy of the fleet to one cloud with the same eval smoke green.

---

## Sequencing notes

- Phases 0→2 are strictly sequential (M1 discipline). Phases 3 and 4 can interleave after M1.
  Phase 5 depends on 3; Phase 6 rolls up everything.
- Model/API choices (Voyage, rerank, VLM OCR, LLM) live behind `packages/common` adapters with
  eval-backed swap criteria — vendor churn is expected mid-2026.
- Every phase updates ADRs and this plan; deviations are recorded, not silently absorbed.
