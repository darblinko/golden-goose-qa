# ADR 0004: Neo4j knowledge graph from day one

Status: accepted (2026-07-17)

## Context
Under QMSR (effective 2026-02-02, 21 CFR 820 incorporating ISO 13485:2016),
FDA inspections follow CP 7382.850 using the risk file as roadmap. Auditor
questions are multi-hop by construction: complaint → failure mode → FMEA row →
mitigation → design output → verification evidence. Vector search alone cannot
answer "show me the traceability" questions.

## Decision
Neo4j Community 5.26 LTS ships in the core fleet from Phase 0. Schema-first
graph (~37 node types incl. DocumentRevision as first-class), deterministic
edge extraction ranked by source reliability (trace matrices > DHF/DMR/RMF
indexes > form fields > revision tables > references > validated regex).
Query access = pre-canned parameterized Cypher tools first, gated read-only
Text2Cypher second.

## Consequences
- The inspection-critical traversals are graph queries with citations, not
  LLM guesses.
- Community edition = single DB, no RBAC in-graph; isolation is enforced at
  the API layer. Acceptable for local/single-tenant; revisit for cloud.
