# ADR 0009: Hosted inference behind provider seams with deterministic fakes

Status: accepted (2026-07-17)

## Context
The dev machine has no GPU and ~10 GB RAM; local embedding/rerank/OCR models
are not viable at quality. Hosted APIs (Anthropic LLM, Voyage embeddings +
rerank, Gemini-class VLM OCR) are the quality bar, but tests and offline dev
must not depend on network or keys — and a fake must never silently answer
where real inference was demanded.

## Decision
Four ABCs (LLMProvider, EmbeddingProvider, RerankProvider, OCRProvider) with
httpx-based real adapters (no vendor SDKs) and deterministic fakes.
`build_providers` selects real iff the key is present; if
`GG_REQUIRE_REAL_PROVIDERS=true` and a key is missing, startup fails with
MissingProviderKeyError. `ProviderSet.using_fakes` is logged and exposed in
`/ready` so a fake can never masquerade.

## Consequences
- Unit/CI runs are hermetic and deterministic; live-API tests carry the
  `external` marker and skip without keys.
- Model churn = config + one adapter, never a codebase sweep.
- OCR confidence gating (Phase 4) is enforceable because OCRPage carries
  confidence and warnings as data.
