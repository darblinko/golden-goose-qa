# ADR 0017: OpenTelemetry tracing seam and an in-process cost ledger

Status: accepted (2026-07-18)

## Context
Phase 6 needed per-turn observability: which nodes ran, how long retrieval
and generation took, and what each turn cost in tokens and dollars. ADR 0008
already picked Phoenix as the trace UI, but wiring OTel exporters directly
into agent nodes would couple every node to telemetry configuration, and a
keyless dev environment (fake providers) has no natural place to read token
prices from.

## Decision
- Tracing goes through one seam: `gg_common.tracing.setup_tracing()` is
  called once at app startup and returns a no-op tracer unless
  `OTEL_EXPORTER_OTLP_ENDPOINT` is configured. Nodes and tools create spans
  through `gg_common.tracing.tracer()`; they never import OTel SDK classes.
  With the `obs` compose profile up, spans land in Phoenix; without it, the
  same code runs with zero overhead and zero configuration.
- Cost is tracked by an in-process ledger (`gg_common.costs`): a contextvar
  scoped to the request accumulates prompt/completion token counts and
  computed dollar cost per provider call. Provider adapters report usage into
  the ledger; on a successful chat turn the API surfaces the turn total in the
  SSE `done` payload, in a structured per-turn log line, and as span
  attributes. Fake providers report zero cost, so the plumbing is identical
  keyed and keyless.

## Scope (what this phase does and does not do)
- The ledger covers the **interactive chat turn's successful path** only.
  Turn cost is emitted in-band (SSE `done`, log, span) but is **not persisted
  to a database column** — there is no usage/cost table or message-row cost
  field, so cross-conversation aggregation is not yet available from SQL.
- **Failed turns are not costed.** The ledger total is read after the turn
  succeeds; a turn that raises before completion emits an `error` event with no
  usage summary, so retries and failures are not accounted for.
- The **ingestion worker and the advisory-note call** run outside this request
  scope and are not wired to the ledger; their model usage is invisible to it.
- Dollar figures use **static estimated prices** from a local price table.
  A model with no price entry contributes `$0`, which understates rather than
  fails — treat `cost_usd` as an estimate, not a billed figure.
- OpenInference / auto-instrumentation is not installed; spans are created
  manually through the tracing seam.

## Consequences
- Telemetry is opt-in per environment and cannot break a deployment that
  lacks an OTLP endpoint.
- Per-turn cost is observable operationally (log/trace/SSE) but is ephemeral.
  Durable per-conversation aggregation, failure/retry accounting, and unified
  api+worker cost require a persisted usage table and worker instrumentation,
  which are deferred to a later ADR; do not rely on this seam for billing or
  audit-grade cost reporting.
- The ledger only sees calls made through the provider adapters on the request
  path. A future provider integrated outside `gg_common.providers`, or any work
  done off the request scope (worker, background tasks), must be wired to the
  ledger explicitly or its cost is invisible — this is the seam's price.

## Revision history
- 2026-07-18: Narrowed the Decision and Consequences to the behavior actually
  shipped. The prior text claimed the turn total was persisted on the message
  row and that "cost figures live in the chat database and can be aggregated
  with plain SQL." No migration or message SQL carries a cost/token column, and
  failed turns and the worker are uncosted, so those claims were removed and an
  explicit Scope section added. Persisting usage (including failure paths) and
  instrumenting the worker are left to a future ADR rather than asserted here.
