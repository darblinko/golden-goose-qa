# 03 — Storage & Infrastructure Stack Evaluation

Date: 2026-07-17
Scope: production-quality, locally-run (Docker Compose) agentic RAG system; later extension to AWS or Azure (cloud-neutral design).
Constraints: 6 CPU cores, ~10 GB RAM, no GPU (WSL2). Corpus 5k–50k documents (~500k–2M chunks).
Working hypothesis under test: Qdrant + Neo4j + Postgres + MinIO + Next.js + FastAPI/LangGraph, via uv and dotenv.

All version numbers, licenses, and footprint claims below were verified against live sources (GitHub releases, PyPI, vendor docs) on 2026-07-17/18. Vendor benchmark multipliers are treated skeptically and flagged.

**Verdict up front:** the hypothesis survives with two component replacements and three refinements:

| Component | Hypothesis | Verdict |
|---|---|---|
| Vector store | Qdrant | **Keep — Qdrant v1.18.x** |
| Graph DB | Neo4j | **Keep — Neo4j Community (with eyes open on GPLv3 + RAM floor)** |
| Structured/app/state DB | Postgres | **Keep — but pin Postgres 18, not 17/16** |
| Object storage | MinIO | **Replace — MinIO is dead (repo archived Apr 2026). Use SeaweedFS** |
| Task queue | (implicit Celery+Redis) | **Use SAQ on Postgres — drop the Redis container entirely** |
| Auth | (Keycloak candidate) | **No IdP container — library-level auth, OIDC-ready by config** |
| Observability | (Langfuse candidate) | **Langfuse v3 does not fit — use Arize Phoenix (single container)** |

---

## 1. Vector store

### Candidates at a glance (verified 2026-07)

| | Version (date) | License | Native hybrid dense+sparse | RAM @ 1M×768d | AWS managed | Azure managed |
|---|---|---|---|---|---|---|
| **Qdrant** | v1.18.3 (2026-07-17) | Apache-2.0 | Yes — sparse vectors + server-side RRF/DBSF fusion | ~4.6 GB full; **~1–1.5 GB** with int8 quant + on-disk originals | Qdrant Cloud (AWS regions + Marketplace) | Qdrant Cloud (Azure regions + Marketplace) |
| pgvector | v0.8.5 (2026-07-08) | PostgreSQL | Partial — tsvector FTS + manual RRF in SQL; `sparsevec` type but no BM25 scoring | ~3 GB + HNSW; halvable via `halfvec` | RDS 0.8.0 / Aurora 0.8.1 | Azure Flexible Server 0.8.2 (PG13–18) |
| LanceDB | python-v0.34.0 (2026-07-02) | Apache-2.0 | Yes — native BM25 FTS + RRF reranker (in-process) | Embedded, disk-first; hundreds of MB | LanceDB Cloud (beta) / Enterprise (Marketplace) | Enterprise BYOC (MS Marketplace) |
| Weaviate | v1.38.5 (2026-07-16) | BSD-3-Clause | Yes — BM25F + vector, alpha blend, 2 fusion algos | ~6 GB (official 2× rule); RQ ~4x; HFresh disk index (GA 1.38) | Weaviate Cloud + AWS Marketplace | Weaviate Cloud + Azure Marketplace |
| Milvus | v2.6.20 (2026-07-14) | Apache-2.0 | Yes — BM25 function → sparse vectors + RRF/Weighted rankers | RaBitQ −72%, mmap — but standalone documents **8 GB minimum** + etcd + object store | Zilliz Cloud (AWS) | Zilliz Cloud (Azure, BYOC) |
| OpenSearch | 3.7.0 (2026-06-09) | Apache-2.0 | Yes — hybrid query + normalization pipeline (RRF/min_max/z-score); neural sparse | ~3.5 GB HNSW + JVM heap; on_disk 32x BQ mode | Amazon OpenSearch Service (≤3.5) + Serverless | None first-party (Azure AI Search is a different product) |

### Analysis against criteria

- **Hybrid search.** Qdrant, Weaviate, Milvus, and OpenSearch all do real server-side hybrid. Qdrant's Query API is the cleanest for an agentic stack: named sparse vectors, nested `prefetch` for multi-stage retrieval (quantized→full rescore, ColBERT multivectors), RRF and DBSF fusion server-side. pgvector's hybrid is DIY SQL RRF (or ParadeDB `pg_search`, which is AGPL and — critically — **not available on RDS or Azure Flexible Server**, so it breaks the cloud-portability requirement if load-bearing). LanceDB fuses in-process via rerankers (it is embedded; acceptable but couples retrieval quality tuning to app code).
- **Payload filtering/indexes.** Qdrant: payload indexes on keyword/int/float/bool/geo/datetime/UUID + full-text payload index; filters compose with ANN natively. pgvector 0.8+ fixed the classic filtered-ANN under-fetch via iterative index scans. OpenSearch has the richest general faceting but at JVM cost.
- **Memory at our scale.** The decisive criterion on a 10 GB box. Qdrant's official formula (`vectors × dims × 4 B × 1.5`) gives ~4.6 GB for 1M×768d fully in RAM, but int8 scalar quantization (`always_ram`) + original vectors `on_disk` (mmap) drops resident needs to ~1–1.5 GB with two-phase rescoring. TurboQuant (v1.18+) goes further if needed. Weaviate needs RQ/HFresh to fit; Milvus standalone (documented 8 GB min, multi-container with etcd + object store) and OpenSearch (JVM) are disqualified on footprint alone.
- **Snapshots/backup.** Qdrant: per-collection and full snapshots via REST; snapshot storage direct to S3-compatible storage since v1.10 (restore is from local file/URL — use presigned URL). Weaviate's backup API is best-in-class (native S3/Azure/GCS modules, incremental) but doesn't outweigh its RAM cost. pgvector inherits pg_dump/PITR.
- **Multitenancy.** Qdrant's official guidance matches our design: one collection per embedding model, payload-based partitioning by `tenant_id`, `is_tenant=true` keyword index to physically co-locate tenant vectors; v1.16+ tiered multitenancy if this ever becomes a real multi-tenant product.
- **License.** Qdrant, LanceDB, Milvus, OpenSearch: Apache-2.0. Weaviate: BSD-3. pgvector: PostgreSQL license. No BSL/SSPL anywhere in this category. Qdrant's open-core carve-out is Cloud-only; the server is fully OSS.
- **Cloud paths.** Qdrant Cloud runs in AWS *and* Azure regions with marketplace billing on both — the symmetric story we need. pgvector is the only candidate that is first-party managed on both clouds (RDS/Aurora and Azure Flexible Server), which makes it the strongest *fallback*. OpenSearch is asymmetric (great on AWS, absent on Azure).
- **LangChain/LangGraph.** `langchain-qdrant` 1.1.0 (2025-10) exposes `retrieval_mode=HYBRID` using Qdrant's server-side fusion, with `FastEmbedSparse`/`Qdrant/bm25` as the out-of-box sparse encoder — the most mature hybrid integration of the set alongside `langchain-milvus` 0.4.0. LanceDB has **no dedicated package** (community-tier `langchain_community.vectorstores.LanceDB`, dense-only).

### Recommendation

**Qdrant v1.18.x.** It is the only candidate that simultaneously: fits the RAM budget with headroom (quantized), does server-side hybrid fusion, has first-class payload-partitioned multitenancy, is Apache-2.0, has managed cloud on both AWS and Azure, and has a mature hybrid-capable LangChain package.

- **Runner-up / fallback: pgvector.** If operational simplicity ever outweighs hybrid quality (one less container; unbeatable cloud portability), pgvector + tsvector RRF is the graceful degradation path. Keep chunk text + metadata mirrored in Postgres anyway (we do — see §3), so this fallback stays cheap.
- **Config commitments:** scalar int8 quantization with `always_ram: true`, original vectors `on_disk: true`, single `chunks` collection, deterministic point IDs (see §5), payload indexes on `doc_id`, `source_type`, `tenant_id` (as `is_tenant`), `content_hash`.

---

## 2. Graph database

### Candidates at a glance (verified 2026-07)

| | Version (date) | License | Cypher completeness | Footprint | Cloud (AWS / Azure) | Text-to-Cypher ecosystem |
|---|---|---|---|---|---|---|
| **Neo4j Community** | 2026.06.0 (CalVer, 2026-07-08); LTS 5.26.x | GPLv3 (server); Apache-2.0 drivers | Reference implementation (Cypher 5 + Cypher 25) | Heaviest: JVM; ~2 GB container floor | Aura on both AWS and Azure (60+ regions) | Best: langchain-neo4j 0.10.0, neo4j-graphrag 1.17.0 (Text2CypherRetriever) |
| Memgraph | v3.12.0 (2026-07-15) | **BSL 1.1** (→Apache-2.0 per-release after Change Date); Enterprise proprietary | Near-Neo4j openCypher; no `shortestPath()` syntax (own BFS/DFS), no rel constraints | In-memory C++: ~97 MB @ 100k nodes/500k edges; ~1 GB @ 1M/5M. On-disk mode experimental, not for prod | Memgraph Cloud AWS-only; no Azure | langchain-memgraph (2026-05), ai-toolkit; consumes Neo4j-flavored Cypher nearly verbatim |
| FalkorDB | v4.20.1 (2026-07-15) | **SSPLv1** (not OSI) | Subset of openCypher 9 + extensions | Lightest server: Redis module, GraphBLAS sparse matrices; 100 MB-class | FalkorDB Cloud AWS/GCP only; no Azure | GraphRAG-SDK 1.3.0; thinner LangChain support |
| Kuzu | v0.11.3 final (2025-10-10) | MIT | Own dialect, schema-required | Embedded (best) | n/a | **DEAD** — Apple acqui-hired Kùzu Inc. Oct 2025, repo archived; langchain-kuzu archived. Fork LadybugDB v0.17.0 active but young |
| Apache AGE | 1.7.0 (2026-01-21, PG18); 1.6.0 (PG14–17) | Apache-2.0 | Subset via SQL wrapper: no `MERGE ... ON CREATE/MATCH SET`, no datetime fns, no `EXISTS {}` | ~0 marginal (inside Postgres) | **Not on RDS/Aurora**; Azure Flexible Server GA (May 2025, PG18 Apr 2026) | Essentially none; agtype parsing pain; SQL envelope trips LLM-generated Cypher |

### Analysis against criteria

- **Do Neo4j Community's limits matter here?** CE lacks: RBAC (basic auth only), multiple databases (exactly one user DB), online/hot backup (offline `neo4j-admin dump` only), clustering. For a single-application knowledge graph: **no RBAC** is fine — the graph is only reached through the API service, which enforces authorization; **single DB** is fine — one KG per deployment, tenant separation by node property/label if ever needed; **offline backup** is the only real operational wart — dumps require a stop or a filesystem-level volume snapshot; acceptable for this system with a nightly maintenance window. The old 4-core CE limit no longer appears in the current editions table. GPLv3 applies to the server we run unmodified in its own container (not linked into our code — drivers are Apache-2.0), which is a well-trodden, safe pattern.
- **Text-to-Cypher friendliness** is the criterion that dominates for an agentic system, and the ranking is unambiguous: **Neo4j >> Memgraph > FalkorDB >> AGE > Kuzu**. LLMs emit Neo4j-flavored Cypher by default; `neo4j-graphrag-python` (first-party, v1.17.0) ships Text2CypherRetriever and a KG-construction pipeline; `langchain-neo4j` 0.10.0 has Neo4jGraph + GraphCypherQAChain. AGE's SQL envelope (`SELECT * FROM cypher('g', $$...$$) AS (v agtype)`) plus missing `MERGE ON CREATE`/temporal functions makes naive LLM generation fail constantly; its Python driver story (ANTLR agtype parsing) is the weakest of the set.
- **Kuzu is eliminated on project health**: Apple acquired Kùzu Inc. (agreement 2025-10-09, confirmed by UWaterloo and EU regulatory disclosure), the repo was archived 2025-10-10, and `langchain-kuzu` is explicitly archived on PyPI. LadybugDB (v0.17.0, 2026-05) is a credible fork but too young to bet a production system on.
- **Memory**: the honest cost of choosing Neo4j. Docs starting point is 1 GB heap + pagecache + JVM overhead → ~2 GB container. Our KG at 5k–50k docs will hold on the order of 10⁵–10⁶ nodes; store size well under 1 GB, so 768 MB heap + 512 MB pagecache inside a 2 GB limit is comfortable (`neo4j-admin server memory-recommendation` to tune). Memgraph would cost ~1 GB and FalkorDB ~100 MB for the same graph — they are the pressure-relief valves if the budget tightens.
- **Cloud symmetry**: Neo4j Aura is the *only* managed graph on both AWS and Azure (free tier 200k nodes/400k rels; Professional from $65/GB/mo). Memgraph Cloud is AWS-only; FalkorDB Cloud is AWS/GCP-only; AGE is Azure-only (GA on Flexible Server) and impossible on RDS. Self-hosting CE containers on ECS/AKS is unrestricted under GPLv3.
- **Multi-hop performance**: all vendor claims (Memgraph benchgraph, FalkorDB "374x") are vendor-run — flagged, not relied on. At our graph size (≤1M nodes), 2–4-hop traversals are fine on any of these engines; performance does not discriminate at this scale.

### Recommendation

**Neo4j Community 2026.06 (or 5.26 LTS for a longer support runway — LTS until June 2028).** Chosen for the text-to-Cypher/GraphRAG ecosystem and the symmetric Aura cloud path; the 2 GB RAM floor is the price and it fits the budget (§8).

- **Documented fallback: FalkorDB** if the fleet ever needs the RAM back (~100 MB, GraphRAG-SDK, but SSPL and no Azure managed path). Keep all graph access behind a repository interface and generate standard Cypher, so a swap stays feasible.
- **Rejected**: Memgraph (BSL fine in practice, but in-memory-only production mode + AWS-only cloud), AGE (Cypher gaps break LLM generation; driver friction; no AWS path), Kuzu (dead).

---

## 3. Postgres: role and schema design

### Version and image

**Pin Postgres 18** (not 17 or 16). PG18 GA'd 2025-09-25 (current 18.4), is ~10 months mature, EOL Nov 2030, and the ecosystem has caught up: Aurora PG18 GA since June 2026, Azure Flexible Server PG18 GA, and the `pgvector/pgvector:pg18-*` Docker images (bundling pgvector 0.8.5) are actively maintained. PG18 brings async I/O (`io_method=worker`/`io_uring`, 2–3x on scans/vacuum), B-tree skip scan, `uuidv7()`, and virtual generated columns; PG17's incremental backup (`pg_basebackup --incremental`) is inherited. Pin 17 only if a required extension lags — none of ours do.

**Image:** `pgvector/pgvector:pg18-trixie` — one container serves app state, registers, checkpoints, audit, the task queue (§5), and the pgvector fallback (§1).

**Extensions** (all verified PG18-compatible): `pgvector` 0.8.5 (≥0.8.2 mandatory — CVE-2026-3172 buffer overflow in parallel HNSW builds), `pg_trgm` + `pgcrypto` (contrib, in-image), `pg_partman` 5.4.3 (PG18 quirk: parent table cannot be UNLOGGED), `pg_cron` 1.6.7. ParadeDB `pg_search` 0.24.3 works locally but is **not** on RDS/Azure — do not make it load-bearing.

### Schema design: four concerns, four schemas

One database, four schemas with distinct access roles — this keeps text-to-SQL sandboxed and the audit log tamper-resistant:

```
app_db
├── registers   -- (a) extracted structured records — the text-to-SQL surface
├── app         -- (b) users, sessions, chat threads/messages
├── checkpoints -- (c) LangGraph checkpointer tables (managed by the library)
└── audit       -- (d) append-only audit log
```

**(a) `registers` — extracted structured registers (NCR/CAPA/complaint logs) for text-to-SQL.**
- Strongly typed, boring relational tables: `ncr(id, doc_id, ncr_number, raised_date, severity, status, description, ...)`, `capa(...)`, `complaint(...)`. Every row carries `doc_id` + `source_span` back-references to the source document (provenance for citations).
- Constrained vocabularies as `CHECK` constraints or lookup tables (status/severity enums) — the LLM writes better SQL against explicit enums, and invalid extractions fail loudly at insert.
- Expose **views** (`registers.v_*`) to the text-to-SQL agent, and run its queries under a dedicated role: `GRANT SELECT ON ALL TABLES IN SCHEMA registers TO textsql_ro;` with `default_transaction_read_only = on` and a `statement_timeout`. The agent role can never see `app`, `checkpoints`, or `audit`.
- Extraction writes are idempotent upserts keyed on `(doc_id, register_type, natural_key)` so re-ingestion doesn't duplicate rows (§5).

**(b) `app` — users, sessions, chat threads.**
- `users` (OIDC-ready: `subject` + `issuer` columns from day one, so an external IdP can be swapped in without a migration — see §6), `sessions`, `threads`, `messages` (thread_id FK, role, content JSONB, token counts), `documents` (registry: id, uri in object storage, `content_hash`, `version`, mime, status, timestamps — the ingestion source of truth, §5).
- `uuidv7()` (native in PG18) for all PKs: time-ordered, index-friendly.

**(c) `checkpoints` — LangGraph.**
- `langgraph-checkpoint-postgres` **3.1.0** creates 4 tables via `.setup()`: `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`. Verified pitfalls to encode in the bootstrap script:
  - `.setup()` must run once on a connection with `autocommit=True` (it issues `CREATE INDEX CONCURRENTLY`);
  - pool kwargs: `{"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}` (prepared-statement clashes otherwise);
  - use `AsyncPostgresSaver` without pipeline mode (known pipeline bugs with `AsyncConnectionPool`);
  - set `LANGGRAPH_STRICT_MSGPACK=true` to constrain checkpoint deserialization.
- Point the saver at the `checkpoints` schema via `search_path` on its dedicated role. Add a `pg_cron` job to prune checkpoints for threads older than the retention window — checkpoint tables grow fast under agentic loops.

**(d) `audit` — immutable audit log.**
- Canonical pattern (PostgreSQL wiki "Audit trigger 91plus" + hash chaining):

```sql
CREATE TABLE audit.log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    actor       text NOT NULL,          -- user subject or service name
    action      text NOT NULL,          -- e.g. 'doc.ingest', 'chat.query', 'register.update'
    entity      text,
    payload     jsonb NOT NULL,
    prev_hash   bytea NOT NULL,
    row_hash    bytea NOT NULL          -- sha256(canonical(fields) || prev_hash), via pgcrypto digest()
);
REVOKE UPDATE, DELETE, TRUNCATE ON audit.log FROM PUBLIC, app_rw;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit.log
    FOR EACH ROW EXECUTE FUNCTION audit.raise_immutable();  -- RAISE EXCEPTION
```

- Key caveat from the canonical reference: in-database auditing cannot constrain a superuser or the table owner — so the **app role must not own `audit.log`**, and the hash chain (each `row_hash` folds in `prev_hash`) makes any rewrite detectable on replay. If the DBA is in the threat model, HMAC with an externally held key and periodically anchor the chain head outside the DB (e.g. object storage with object lock, §4).
- Partition by month with `pg_partman` if volume warrants; never drop partitions inside the retention window.

**Cloud path:** RDS/Aurora PG18 (pgvector 0.8.0/0.8.1 — verify the CVE-fixed 0.8.2+ has landed on your target minor before relying on parallel HNSW builds) and Azure Flexible Server PG18 (pgvector 0.8.2 allow-listed via `azure.extensions`). Everything in this design is vanilla Postgres + mainstream extensions, so it ports unchanged.

---

## 4. Object storage

### MinIO is disqualified — verified timeline

- AGPLv3 core since 2021; **May 2025**: community web console gutted to a bare object browser (accounts/policies/bucket/lifecycle/OIDC management removed).
- Community edition moved to **source-only distribution** (no pre-built binaries); Docker Hub `minio/minio` last pushed ~Sept 2025 and the repo is **marked Archived**.
- Final community release `RELEASE.2025-10-15` (a CVE fix).
- **2026-04-25: the GitHub repo was archived, read-only**, with a banner pointing to AIStor Free (freeware) and AIStor Enterprise (reportedly ~$96k/yr entry).

Adopting MinIO today means pinning an archived AGPL codebase with no future security patches. **The working hypothesis must change here.**

### Alternatives (all verified active)

| | Version (date) | License | S3 API coverage | Footprint | Notes |
|---|---|---|---|---|---|
| **SeaweedFS** | 4.39 (2026-07-10, ~weekly cadence) | Apache-2.0 | Near-complete: versioning, **object lock/retention/legal hold**, tagging, multipart, presigned URLs, SSE-S3/KMS/C, bucket policies, STS/OIDC | ~387 MB idle reported (community-measured); scales with in-flight I/O, not file count | Single `weed server -s3` binary runs master+volume+filer+S3 in one process |
| Garage | v2.3.0 (2026-04-16) | AGPL-3.0 | Core ops, multipart, presigned, SSE-C, lifecycle-expiry. **No versioning, no object lock, no tagging, no bucket policies** | Lightest (Raspberry-Pi-class; Rust; SQLite metadata) | v2.3 added single-node autocreation — great dev ergonomics |
| versitygw | v1.7.0 (2026-07-15) | Apache-2.0 | Growing subset; stateless S3→POSIX translation — objects are plain files on the volume | Tiny (Go binary) | **Has a native Azure Blob backend** — same shim fronts Blob in a cloud port |
| RustFS | ~1.0.0-alpha | Apache-2.0 | Markets as MinIO drop-in | — | Too early (alpha; distributed mode unreleased) |

### Recommendation

**SeaweedFS 4.x, single-container (`weed server -s3`), 512 MB limit.** Rationale: Apache-2.0, very active (weekly releases), lightest credible footprint, and — decisive for this system — **object versioning and object lock**, which pair with the audit design: raw source documents and the audit hash-chain anchor (§3d) can be written under retention lock, and doc-version awareness in ingestion (§5) can lean on native versioning.

- Garage is the lighter fallback if versioning/lock are dropped from requirements; versitygw is worth remembering purely for its Azure Blob backend.
- **Portability rule:** application code never imports an S3 SDK directly. One thin `ObjectStore` interface (put/get/presign/delete + bucket conventions), implemented over boto3 (or `obstore`, which is Rust-backed and covers S3+Azure+GCS with one API). Local = SeaweedFS; AWS = S3; Azure = **native Blob via the same abstraction** — do not run an S3 shim in production Azure when the SDK layer makes it unnecessary.

---

## 5. Ingestion pipeline infrastructure

### Task queue (verified 2026-07)

| | Version (date) | License | Async | Broker | Verdict |
|---|---|---|---|---|---|
| Celery | 5.6.3 (2026-03) | BSD-3 | No native async | Redis/RabbitMQ | Prefork = ~2.5 GB for 50 concurrent I/O-bound tasks; oversized and wrong-shaped for LLM workloads |
| arq | 0.28.0 (2026-04) | MIT | Native | Redis | **Maintenance-only mode** (repo banner; v1 never landed) — do not adopt for new builds |
| Dramatiq | 2.2.0 (2026-06) | **LGPL-3.0+** | Via middleware (sync-first) | Redis/RabbitMQ | Solid but LGPL + async-as-afterthought |
| Prefect | 3.7.8 (2026-07) | Apache-2.0 | Yes | Own server | Orchestrator; server wants 4–8 GB — oversized |
| Hatchet | 1.35.0 (2026-07) | — | Yes | Postgres | Credible (Hatchet Lite = 1 container on existing PG) but still an extra service |
| **SAQ** | 0.26.4 (2026-05) | MIT | **Async-native** | Redis **or Postgres** (`saq[postgres]`) | **Pick** — broker-free on our existing PG18 |
| procrastinate | 3.9.0 (2026-06) | MIT | Sync+async | Postgres (LISTEN/NOTIFY) | Strong alternative; most mature PG-native queue |

**Recommendation: SAQ with the Postgres backend** (fallback: procrastinate — near-tie, choose by API taste). This eliminates the Redis container entirely: the queue lives in the PG18 instance we already run, jobs are durable across restarts, and the worker is a single asyncio process. 2026 community guidance explicitly endorses Postgres-backed queues for operational consolidation at moderate volume — and 5k–50k docs is moderate volume.

On a 6-core box the parallelism model is: 1 SAQ worker process, concurrency ~8–16 coroutines for I/O-bound stages (S3 reads, embedding API calls, Qdrant/Neo4j upserts), and a small `ProcessPoolExecutor` (2–3 processes) for CPU-bound parsing (PDF text extraction). Heavy layout-model parsing (docling-class, CPU-only) should be run as a bounded stage, not unbounded parallelism — it is the one thing that can blow the worker's memory limit.

### Incremental re-indexing and idempotency

- **Content hashing:** `documents.content_hash = sha256(bytes)` computed at upload. Re-ingestion of an unchanged file is a no-op (hash match short-circuits). Per-chunk `chunk_hash` for finer-grained skip when only part of a doc pipeline changes (e.g. re-embed without re-parse).
- **Doc versioning:** new hash for an existing logical document → increment `documents.version`, keep the old object under SeaweedFS versioning, re-extract, and replace derived data transactionally per store.
- **Deterministic IDs everywhere = idempotent writes:**
  - Qdrant point ID = UUIDv5 of `(doc_id, chunk_index, chunk_hash)` → re-upsert is naturally idempotent; stale chunks removed by `delete` with a `doc_id` filter + `version < current` payload filter.
  - Neo4j: `MERGE` on stable natural keys (entity canonical ID), relationships carry `doc_id`/`version` provenance properties so a doc's graph contributions can be retracted on re-ingest.
  - `registers`: upsert on `(doc_id, register_type, natural_key)` (§3a).
- **Pipeline as staged jobs with per-stage status** on the `documents` row (`uploaded → parsed → chunked → embedded → graphed → indexed`), each stage idempotent and re-runnable — a crashed worker resumes by re-enqueueing incomplete docs, harmlessly.
- Every state transition writes to `audit.log`.

---

## 6. Backend: FastAPI + LangGraph service layout, streaming, auth

**Versions (verified):** FastAPI 0.139.2 (2026-07-16), LangGraph 1.2.9 (2026-07-10), sse-starlette 3.4.5 (2026-06-20).

### api + worker split — yes, but one image

Two containers from **one Docker image** (same uv-built venv, different entrypoints: `uvicorn` vs `saq worker`). Rationale: ingestion parsing is the only component with CPU/RAM spikes; isolating it means a 2 GB parse cannot OOM the API serving chat. One image keeps the build simple and versions atomically. LangGraph agent execution stays in the API process (agent turns are I/O-bound token streaming — they don't need the worker), with the shared checkpointer in Postgres meaning either process can resume a thread if that ever changes.

### SSE, not WebSocket

Community and LangGraph-Platform consensus is SSE for token streaming: `graph.astream_events()` filtered on `on_chat_model_stream` → `EventSourceResponse` (sse-starlette). WebSocket only if bidirectional needs appear (mid-stream cancel can be done with a separate POST). Next.js App Router gotchas (verified): consume via `fetch` + `response.body.getReader()` (not the EventSource polyfill through Next's server), and set `Cache-Control: no-cache, no-transform` + `X-Accel-Buffering: no` so neither Next nor a proxy buffers the stream.

### AuthN: no IdP container (yet) — OIDC-ready by design

Verified footprints kill the container options on this box: **Keycloak 26.7** needs ~1.25 GB base / 2 GB recommended; **Authentik** is officially 2 GB min / 4 GB recommended across 4 containers; **ZITADEL** v4 (~512 MB–1 GB) is the best IdP-in-a-container option but changed to **AGPL-3.0** with v3 (2025-03); Ory Kratos+Hydra needs two containers plus a self-built login UI. Library layer: **Auth.js v5 never left beta and is in security-fix-only maintenance under the Better Auth team (since 2025-09), which directs new projects to Better Auth**; `fastapi-users` 15.0.5 is officially in maintenance mode.

**Recommendation:**
- **Now:** auth lives in the Next.js layer with **Better Auth** (the actively developed successor; email/password + OIDC client support), sessions minted as short-lived JWTs; FastAPI validates JWT signature + claims on every request (a ~50-line dependency, no container). `app.users` carries `(issuer, subject)` from day one.
- **Later (cloud):** flip the OIDC issuer by env var to Cognito / Entra ID / a managed Keycloak — because FastAPI only ever validated `iss`/`aud`/signature against a JWKS URL, and users are keyed on `(issuer, subject)`, the swap is configuration plus a user-linking migration, not a redesign. This is what "OIDC-ready" buys without spending 2 GB of RAM on day one.

---

## 7. Observability

Verified facts:

- **Langfuse** v3.221.1: MIT (except `ee/`), but v3 self-hosting requires **6 containers** — web + worker + Postgres + **ClickHouse** + Redis + S3 — with official minimums summing far past this machine (ClickHouse alone: 2 CPU/8 GiB recommended). The lighter v2 Postgres-only deployment is **deprecated** (v3 is the only supported path as of May 2026). Does not fit.
- **Arize Phoenix** v19.0.0: **single container**, Elastic License 2.0 (source-available; self-hosting free, no feature gates), SQLite by default (Postgres optional), OpenTelemetry/OpenInference-native with LangChain/LangGraph auto-instrumentors; Arize's own hosted sizing is 1 vCPU/2 GB. Fits.
- **LangSmith**: SaaS (free dev tier; Plus $39/seat/mo); self-hosting is enterprise-only. Zero local RAM — but traces leave the machine.
- **OTel GenAI semconv**: `gen_ai` client spans went **stable in early 2026**; agent/tool-span conventions still experimental. Jaeger all-in-one is a lightweight generic alternative but loses LLM-specific UX (token/cost rollups, evals).

**Recommendation: Arize Phoenix, single container, 768 MB limit, SQLite on a volume**, instrumented via OpenInference/OTel. Because instrumentation is OTel-based, the backend is swappable: point the exporter at LangSmith (SaaS) or a future Langfuse deployment in cloud without touching agent code. Run Phoenix under a Compose `profiles: [observability]` toggle so it can be switched off when the last gigabyte is needed for a heavy ingestion run.

---

## 8. Total memory budget (~8 GB of limits on a 10 GB machine)

Design rules: limits are ceilings, not reservations — steady-state RSS should sit around 5–6 GB; WSL2 itself + OS page cache need the remaining headroom. Heavy ingestion and heavy query load are not run concurrently (the worker's parse pool is bounded, §5).

### Recommended docker-compose fleet

| Container | Image | Role | Mem limit | Notes |
|---|---|---|---|---|
| `qdrant` | `qdrant/qdrant:v1.18` | Vectors + hybrid search | **1.5 GB** | int8 scalar quant `always_ram`, originals `on_disk`; holds 1–2M chunks in ~1–1.5 GB |
| `neo4j` | `neo4j:2026.06-community` (or `5.26-community` LTS) | Knowledge graph | **2.0 GB** | `NEO4J_server_memory_heap_max__size=768m`, `pagecache_size=512m`; largest line item, fits ≤1M-node KG |
| `postgres` | `pgvector/pgvector:pg18-trixie` | Registers, app state, LangGraph checkpoints, audit log, SAQ queue, pgvector fallback | **1.0 GB** | `shared_buffers=256MB`; extensions: vector 0.8.5, pg_trgm, pgcrypto, pg_partman, pg_cron |
| `seaweedfs` | `chrislusf/seaweedfs` (4.x) | S3-compatible object storage | **512 MB** | `weed server -s3`; versioning + object lock on |
| `api` | local build (uv, python:3.13-slim base) | FastAPI + LangGraph agents, SSE | **768 MB** | uvicorn, 2 workers |
| `worker` | same image as `api` | SAQ ingestion worker | **1.25 GB** | Bursts during parse; bounded process pool (2–3) for CPU-bound parsing |
| `web` | local build (Next.js standalone) | Frontend + Better Auth | **512 MB** | `output: "standalone"` |
| `phoenix` | `arizephoenix/phoenix:v19` | Agent/LLM tracing (OTel/OpenInference) | **768 MB** | SQLite on volume; Compose profile — optional |
| **Total** | | | **8.3 GB limits** | ~7.5 GB with `phoenix` off; expected steady-state RSS ≈ 5–6 GB |

*(No Redis container — the queue is Postgres-backed. No IdP container — auth is library-level. That is ~1.5–2.5 GB reclaimed vs the naive fleet.)*

### Explicitly does NOT fit (and the lighter substitution made)

| Doesn't fit | Why | Substitution |
|---|---|---|
| Langfuse v3 | 6-container stack incl. ClickHouse (2C/8Gi rec.) | Phoenix single container; OTel keeps Langfuse possible in cloud |
| Keycloak / Authentik | 1.25–2 GB / 2–4 GB multi-container | Library-level JWT + OIDC-ready `(issuer, subject)` design |
| Milvus Standalone | Documented 8 GB minimum + etcd + object store | Qdrant |
| OpenSearch | JVM + ~3.5 GB HNSW; Azure-asymmetric anyway | Qdrant (hybrid native) |
| Weaviate unquantized | 2× rule → ~6–8 GB at our scale | (rejected; Qdrant quantized) |
| Celery prefork fleet | ~2.5 GB at useful concurrency + Redis | SAQ on Postgres, 1 async worker |
| Neo4j — *if* the box shrinks further | 2 GB floor is the biggest single line | FalkorDB (~100 MB, SSPL) behind the graph repository interface |

Scale note: at the 2M-chunk top end, Qdrant's quantized resident set stays in budget, but if recall tuning demands larger `oversample`/full-precision rescoring throughput, the first lever is raising `qdrant` to 2 GB and turning `phoenix` off locally.

---

## 9. uv-based Python project layout

**uv 0.11.x** (0.11.29, 2026-07-15; weekly cadence). Workspaces are mature and officially documented, including the Docker story.

### Workspace monorepo (recommended over single pyproject)

```
golden-goose/
├── pyproject.toml            # workspace root: [tool.uv.workspace] members = ["apps/*", "packages/*"]
├── uv.lock                   # ONE lockfile for the whole workspace
├── .python-version           # 3.13
├── apps/
│   └── api/                  # FastAPI + LangGraph service (also the worker entrypoint)
│       └── pyproject.toml    # depends on packages via {workspace = true}
├── packages/
│   ├── common/               # settings (pydantic-settings + dotenv), models, ObjectStore/Graph/Vector interfaces
│   ├── ingestion/            # parsing, chunking, hashing, SAQ tasks
│   ├── retrieval/            # hybrid search, reranking, register text-to-SQL
│   └── agents/               # LangGraph graphs, prompts, tools
└── web/                      # Next.js (outside the uv workspace)
```

Why workspace, not one flat pyproject: enforced boundaries between ingestion/retrieval/agents (imports are declared dependencies, not accidents), per-package tests, and Docker layer caching that actually works — while one lockfile keeps resolution consistent (the documented uv model: single `requires-python`, single lock). Members needing conflicting deps would need path-deps instead; we have none.

### Docker build (per uv's official guide)

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
# deps layer: lockfile only, no source — cached until dependencies change
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-workspace --no-dev
COPY apps/ packages/ ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.13-slim-trixie
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
# entrypoint set per-service in compose: uvicorn vs saq
```

`--no-install-workspace` is the documented flag for caching the third-party layer in workspaces; one image serves both `api` and `worker` (§6).

### Python pin: 3.13

Verified ecosystem state (mid-2026): PyTorch 2.13 supports 3.10–3.14; onnxruntime ships cp313/cp314 wheels; LangChain 1.3.x supports 3.10–3.14 — but **langgraph's classifiers still stop at 3.13**. So: `.python-version = 3.13`, `requires-python = ">=3.12"`. 3.12 gains nothing; 3.14 is premature for this stack by one dependency.

Config: `pydantic-settings` + `.env` (dotenv) per the hypothesis; every external endpoint (Qdrant URL, Neo4j URI, S3 endpoint, OIDC issuer, OTel exporter) is env-driven — which is precisely what makes the local→AWS/Azure port a config change per component.

---

## Appendix: hypothesis changes, summarized

1. **MinIO → SeaweedFS.** MinIO community is archived (Apr 2026), source-only, unpatched since Oct 2025. SeaweedFS: Apache-2.0, weekly releases, versioning + object lock, ~0.4 GB.
2. **Postgres 16/17 → 18.** GA since Sept 2025, ecosystem (Aurora, Azure, pgvector images) caught up; async I/O + `uuidv7()` are directly useful.
3. **(Implicit Celery+Redis) → SAQ on Postgres.** Drops a container and ~2 GB of prefork RAM; async-native; durable.
4. **No Keycloak container.** 1.25–2 GB doesn't fit; Better Auth + JWT validation with `(issuer, subject)` user keys keeps the OIDC swap a config change.
5. **No Langfuse locally → Phoenix.** Langfuse v3 mandates ClickHouse (6 containers). Phoenix is one container; OTel instrumentation keeps every backend reachable later.
6. **Qdrant and Neo4j confirmed** — Qdrant on hybrid+quantization+dual-cloud; Neo4j on text-to-Cypher ecosystem + Aura on both clouds, with FalkorDB documented as the RAM-relief fallback and Kuzu eliminated (project dead — Apple acqui-hire, Oct 2025).
