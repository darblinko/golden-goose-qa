# ADR 0008: Arize Phoenix for LLM observability

Status: accepted (2026-07-17)

## Context
Agentic RAG is undebuggable without traces (which subgraph ran, what was
retrieved, why the grader rewrote). Langfuse v3 was the original hypothesis
but now requires ClickHouse + Redis + S3 — three services of overhead.
Phoenix v19 is a single container with OTLP ingest and RAG-native evals.

## Decision
Arize Phoenix (`arizephoenix/phoenix:version-19.0.0`) under the `obs` compose
profile. Instrumentation via OpenTelemetry/OpenInference in the api and worker;
spans are standard OTLP, so a cloud deployment can point the same exporter at
any OTLP backend.

## Consequences
- Full agent traces (retrieval hits, rerank scores, grader verdicts) in one UI.
- The obs profile is optional — the core fleet runs without it on constrained
  machines.
- No vendor lock: swapping backends is an exporter endpoint change.
