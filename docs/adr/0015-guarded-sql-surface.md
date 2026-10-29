# ADR 0015: Guarded SQL surface — curated views, stacked guards, saved queries first

Status: accepted (2026-07-18)

## Context
The warehouse tool lets the agent answer count and listing questions with SQL
during a live audit. Model-authored SQL over quality records carries two
risks: destructive or schema-probing statements, and confidently wrong
queries against tables whose semantics the model guessed. The tool must be
read-only by construction, not by prompt.

## Decision
Three independent layers stand between the agent and the data:

1. **Curated surface.** The tool can only reference the `registers.v_*`
   views — never base tables. The views bake in the derived semantics
   (`is_open`, `age_days`, `effectiveness_overdue`, `ap_mismatch`) so queries
   stay trivial. `REGISTER_VIEWS` in code is the contract; an integration
   test asserts it matches the live views column-for-column.
2. **Static validation.** `sqlguard.validate_select` parses the statement to
   an AST (sqlglot, Postgres dialect) and accepts exactly one SELECT / set
   operation whose every base relation is a whitelisted view — a quoted
   relation, a table-valued function (`unnest`, `read_csv_auto`), or a
   derived-table alias is judged by structure, not by how it lexes. Lexical
   pre-checks still refuse what a parser silently absorbs (comments) or mangles
   (dollar-quoting, unterminated strings); everything else is rejected before
   execution.
3. **Database enforcement.** Execution runs in a read-only transaction under
   `SET LOCAL ROLE sql_tool_ro`, whose grants are scoped to exactly the nine
   `registers.v_*` views (migration 0007) — the role cannot read the base
   tables directly. The two restricted views are `security_invoker` over
   RLS-protected `registers.complaint` / `registers.mdr`, so the role keeps
   SELECT on those two base tables only, with the restricted_read policy (0005)
   filtering rows and failing closed on an unset flag. A statement timeout and
   a row cap bound cost; the session is always rolled back so no flag leaks
   into the pool.

Saved queries covering the standing audit questions (open CAPAs, overdue
effectiveness checks, complaints without risk evaluation, ...) are preferred;
ad-hoc SQL is the exception. Every result carries the executed SQL for the
audit trail.

## Consequences
- All three layers must fail simultaneously before a harmful statement runs;
  layers 2 and 3 now enforce the same views-only boundary layer 1 declares, so
  a whitelist expansion alone cannot reach the base tables.
- Adding a queryable fact means adding it to a view and the drift map — a
  deliberate, reviewed act rather than an emergent model capability.
- The row cap and timeout bound worst-case cost during a live audit;
  truncation is flagged on the result, never silent.
