# ADR 0012: Local BM25 sparse vectors instead of a learned sparse model

Status: accepted (2026-07-18)

## Context
Hybrid retrieval needs a sparse (lexical) leg beside dense embeddings.
Learned sparse models (SPLADE and successors) score well but require model
inference at both index and query time — a GPU-or-slow dependency the local
deployment should not need. QMS language is dominated by exact identifiers
(SOP-004, CAPA-2024-011, ISO 13485 clause numbers) where classic lexical
matching is already near-optimal.

## Decision
Sparse vectors are BM25 lexical weights, split across client and server:

- **Client-side, at chunk time** (`gg_common.sparse.document_sparse_vector`):
  tokenize, hash each term to a uint32 index, and emit the BM25
  term-frequency component with length normalization
  (`tf·(k1+1) / (tf + k1·(1 − b + b·|d|/avgdl))`). Query-side weighting reuses
  the same tokenizer with unit term weights.
- **Server-side, in Qdrant**: the named sparse vector carries Qdrant's IDF
  `Modifier`, so the inverse-document-frequency factor is computed and kept
  current by Qdrant over the live collection. The client never holds or
  refreshes corpus-frequency statistics.

Fusion with the dense leg happens in Qdrant's server-side hybrid query (RRF),
then the reranker orders the fused candidates.

`avgdl` (average document length) is a corpus-derived constant, not a live
statistic: it is the mean child-chunk length — measured in `sparse.tokenize`
tokens — over the seeded reference corpus (≈42 at the shipped
`child_chunk_tokens=350` default). A provenance test regenerates the corpus,
recomputes the mean, and fails if the shipped constant drifts, so the value
stays honest without a runtime statistics store.

## Consequences
- Fully deterministic and dependency-free on the client: the fake-provider CI
  path exercises the same sparse pipeline as production, which is why the
  smoke recall gate (recall@10 >= 0.8) holds with fake embeddings.
- IDF needs no maintenance task — Qdrant recomputes document frequencies as
  the collection changes. Only `avgdl` is pinned to the corpus, and its
  provenance test flags when a corpus change would move it.
- A learned sparse model can later occupy a second named sparse slot for
  A/B comparison without a reindex of the BM25 slot.

## Revision history
- 2026-07-18 (initial): described corpus statistics as "kept in Postgres" with
  a document-frequency "refresh" maintenance task tracked by the registry, and
  left `avgdl` as an unexplained literal.
- 2026-07-18 (corrected): the shipped design delegates IDF to Qdrant's
  server-side modifier — there is no Postgres statistics store and no refresh
  task — and `avgdl` is now a corpus-derived, provenance-tested constant
  rather than the earlier magic number.
