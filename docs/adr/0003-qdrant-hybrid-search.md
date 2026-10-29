# ADR 0003: Qdrant for hybrid dense+sparse retrieval

Status: accepted (2026-07-17)

## Context
State-of-the-art retrieval needs dense semantic vectors, BM25-style sparse
keyword match (regulated QA is full of exact tokens: "21 CFR 820.30",
"CAPA-2024-0031"), server-side fusion, and rich payload filtering — at
5k–50k documents locally on a 10 GB machine.

## Decision
Qdrant v1.18.3 (Apache-2.0), one collection, named vectors:
- dense: voyage-4-large 1024-dim, int8 scalar quantization
- sparse: Qdrant-side BM25 sparse vectors with IDF modifier
- server-side RRF fusion via the Query API prefetch mechanism
- payload indexes on doc_type, status, product, department for filtered search

## Consequences
- One query round-trip returns fused candidates; rerank happens app-side.
- ACL and effectivity ("as of audit date") become payload filters injected
  server-side by our API — never assembled by the LLM.
- int8 quantization keeps the 50k-doc corpus within the 1.5 GB memory limit.
