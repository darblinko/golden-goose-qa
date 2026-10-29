# ADR 0010: Append-only hash-chained audit log enforced in Postgres

Status: accepted (2026-07-17)

## Context
A tool used during regulatory audits must itself be defensible: who asked
what, what was retrieved, what was answered — tamper-evident, and read-only
with respect to history. Application-level "we never call UPDATE" is not a
guarantee; 21 CFR Part 11 expectations favor system-enforced controls.

## Decision
`audit.audit_log` in Postgres with:
- BEFORE INSERT trigger computing `row_hash = sha256(prev_hash | actor |
  action | payload::text | occurred_at_utc_text)`, genesis 32 zero bytes,
  serialized by an advisory xact lock; the trigger also assigns `id` under
  that lock (migration 0006) — an identity column assigned ids before the
  lock, so concurrent inserts could fork the chain
- BEFORE UPDATE/DELETE (row) and BEFORE TRUNCATE (statement) triggers raising
  an exception — this blocks the table owner too, not just gg_app
- grants: gg_app has SELECT+INSERT only; the table is owned by the admin role
- `gg_common.audit.compute_row_hash` mirrors the trigger byte-for-byte;
  `verify_chain` walks the chain and is exercised in integration tests

## Consequences
- Tampering requires DDL (dropping the trigger) as admin, which is itself
  visible in migrations/backups — the threat model is honest.
- The hash material spec lives in exactly two places (trigger, Python mirror)
  and a CI test fails if they diverge.
- Verification is exposed as an operational check, not a promise.
