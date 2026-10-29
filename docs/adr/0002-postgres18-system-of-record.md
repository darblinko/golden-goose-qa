# ADR 0002: Postgres 18 as system of record with four schemas

Status: accepted (2026-07-17)

## Context
We need durable app state, structured QMS registers for the SQL tool, LangGraph
checkpoints, and an immutable audit trail — without multiplying databases.

## Decision
One Postgres 18 instance (pgvector/pgvector:pg18-trixie image) with four
schemas and role separation:
- `app` — documents, chunks (parents), users, conversations (owner: admin;
  gg_app read/write)
- `registers` — structured registers (NCR/CAPA/complaints…) queried by the SQL
  tool via the NOLOGIN `sql_tool_ro` role (SELECT only, enforced by grants)
- `checkpoints` — LangGraph PostgresSaver tables
- `audit` — append-only hash-chained audit log (see ADR 0010)

The pgvector extension is available but Qdrant remains the primary vector
store (ADR 0003); pgvector is a fallback seam, not a second index to maintain.

## Consequences
- One backup/restore story covers app state, registers, checkpoints, audit.
- Text2SQL runs under `SET ROLE sql_tool_ro`; a prompt-injected DML attempt
  fails at the grant layer, not in prompt engineering.
