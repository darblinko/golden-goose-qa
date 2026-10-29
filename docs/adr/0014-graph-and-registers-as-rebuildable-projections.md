# ADR 0014: Knowledge graph and registers are rebuildable projections of parse artifacts

Status: accepted (2026-07-18)

## Context
Phase 3 adds a Neo4j knowledge graph and a `registers` warehouse in Postgres.
Both must stay consistent with what retrieval indexed: an auditor following a
graph edge or a register row must land on the same document content a citation
points at. Two designs were considered: incremental extraction maintained
alongside ingestion (update graph and rows as documents change), or a derive
pass that rebuilds both stores from already-parsed artifacts.

## Decision
Graph and registers are derived projections, rebuilt by `gg-ingest derive`:

- The derive pass reads the `parse.json` artifact of the latest indexed
  version of every document — extraction never re-parses source bytes, so the
  projections always describe exactly what retrieval indexed.
- Extractors are pure functions per document type emitting whitelisted node
  labels and relationship types; every edge carries provenance (extraction
  method) and confidence. Unresolvable references are reported as dangling,
  never silently dropped.
- Each derive wipes derived graph data (everything except migration tracking)
  and MERGE-loads nodes then edges; registers load in one transaction. Both
  are recorded in the append-only audit log.
- Cypher schema migrations are versioned files applied by
  `gg-ingest graph-migrate`, mirroring Alembic on the Postgres side.

## Consequences
- Re-derive is idempotent and removed references never linger; there is no
  incremental bookkeeping to get wrong.
- A full rebuild is O(corpus), acceptable at QMS scale (hundreds to low
  thousands of documents); if corpora grow past that, incremental derivation
  can be added behind the same CLI without changing consumers.
- The integration suite derives the projections from the ingested corpus and
  asserts the seeded defects are discoverable by direct graph and SQL queries,
  so extraction regressions fail CI rather than surfacing mid-audit.
