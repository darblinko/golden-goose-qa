# SOTA Hybrid RAG Architecture for Regulatory Audit Q&A (mid-2026)

Research report for a LangGraph-based agentic RAG system answering questions during live
regulatory audits at a Class 3 medical device company.

- Corpus: 5k-50k heterogeneous quality-system documents (narrative SOPs, Excel FMEA
  matrices, scanned batch records, complaint forms).
- Constraints: hosted APIs allowed for LLM/embeddings/reranking; storage hypothesis
  Qdrant + Neo4j + Postgres; answers must be citation-grounded (an unsupported answer in
  front of an FDA/notified-body auditor is worse than "I don't know").
- All model/API claims below were verified against vendor docs or current benchmarks in
  July 2026; sources listed at the end of each section.

---

## 1. Parsing and extraction

### Recommendation

Route by document class rather than picking one parser:

| Document class | Primary | Fallback / notes |
|---|---|---|
| Born-digital PDF, DOCX (SOPs, protocols, reports) | **Docling** (self-hosted) | LlamaParse for pathological layouts |
| Excel FMEA / matrices (XLSX) | **Native structured extraction** (openpyxl/pandas), not a PDF-style parser | Docling XLSX backend acceptable for simple sheets |
| Scanned batch records, complaint forms | **VLM OCR: Gemini 3 Flash (hosted)** or **olmOCR 2 / Surya 2 (self-hosted)** | Azure Document Intelligence prebuilt-layout if Azure-aligned |
| Checkbox/selection-mark forms | Azure DI layout (selection marks) or VLM prompting | Docling checkbox handling is immature |
| Signature blocks | VLM detection prompt (presence + region + printed name/date), or Azure DI custom neural signature fields | Never claim signer identity; record presence only |

### Justification

**Docling** (IBM/LF AI, open source) is the strongest self-hostable default in 2026:
layout analysis, reading order, TableFormer table-structure extraction (~97.9% accuracy on
complex-table benchmarks in independent evals), code/formula recognition, a lossless
`DoclingDocument` JSON representation that preserves heading hierarchy and provenance
(page + bounding box per element — exactly what citation grounding needs), an optional VLM
pipeline (Granite-Docling), and first-party LangChain/LlamaIndex integrations plus a
`HybridChunker`. On the opendataloader-bench 200-PDF benchmark Docling scores 0.877 vs
marker 0.861 and MinerU 0.831. Self-hosting matters here: QMS content is sensitive, and a
local parser removes one data-processor from the compliance surface. Its per-element
provenance also feeds "cite page N of SOP-023 rev C" directly.

**Scanned documents**: VLM-based OCR has decisively passed classical OCR. Tesseract is no
longer competitive for degraded scans, handwriting (operator entries on batch records), or
form structure — VLMs show 3-4x lower character error rates on noisy scans. As of early
2026 the OCR Arena leaderboard is topped by Gemini 3 Flash, then Gemini 3 Pro, Claude Opus
4.6, GPT-5.2. On olmOCR-bench (1,403 PDFs / 7,010 unit tests), olmOCR 2 scores 82.4 and
Datalab's Surya 2 scores 83.3 — both open weights, both above marker (76.1) and MinerU
(75.8). Practical choice: Gemini 3 Flash for hosted throughput/cost; olmOCR 2 or Surya 2
if scanned batch records must stay on-prem. Run OCR output through the same
DoclingDocument normalization so downstream chunking is uniform, and store an
`ocr_confidence` flag per page so the agent can hedge on low-confidence content.

**Excel FMEA matrices**: PDF-style parsers destroy what makes an FMEA useful — the
row-as-record semantics (failure mode, effect, severity, occurrence, detection, RPN, risk
control, verification link). Parse XLSX natively with openpyxl: detect header rows
(including two-level merged headers common in FMEA templates), extract each data row as a
key-value record, preserve sheet name, and capture cell formats (dates, numbers) exactly.
This feeds row-level chunking (section 2) and KG extraction (section 6) losslessly.

**Checkboxes/forms**: Azure Document Intelligence's layout model (v4.0) extracts selection
marks natively (rendered as ☒/☐ Unicode in output) and is the most reliable managed
option for checkbox-heavy complaint forms; its custom neural model supports trained
key-value + signature-field extraction if you standardize on a small set of form
templates. If avoiding Azure, a VLM prompt ("transcribe this form; render checkboxes as
[x]/[ ]; mark signature blocks as `[SIGNATURE PRESENT: <printed name>, <date>]`") performs
comparably on modern frontier VLMs and needs no training.

**Signature blocks**: no prebuilt hosted model extracts signatures generically (Azure's
prebuilt models do not expose a signature field except the US-check model). The workable
pattern for batch records is detection-of-presence: VLM or Azure custom neural flags that
a signature exists in a labeled block, plus the adjacent printed name/date. Emit this as
structured metadata (`signed: true/false, signed_by_printed: ..., signed_date: ...`) —
auditors ask "was step 12 signed and dated?" constantly. Never assert signer identity from
the mark itself.

### Alternatives considered

- **LlamaParse**: excellent quality and very fast (~6s/doc), agentic parsing modes; but
  hosted-only (data leaves your boundary per page), per-page cost at 50k docs, and known
  multi-column interleaving issues. Keep as targeted fallback.
- **unstructured.io**: widest format support (30+), but independent benchmarks show
  inconsistent complex-table fidelity and it is slow (~51s for 1 page in one 2026 eval).
  Not needed given Docling covers the format list here.
- **marker**: fast, good Markdown, but scores below Docling/olmOCR 2/Surya 2 on current
  benchmarks; its ecosystem (Datalab) now pushes Surya 2 as the quality path.
- **Reducto**: #1 on micro1's LongExtractBench (99.6% P/R, June 2026) — best-in-class
  managed extraction if budget allows; commercial, closed. Reasonable premium alternative
  to the whole parsing tier.
- **Amazon Textract / Google Document AI**: solid forms/tables OCR but no advantage over
  Azure DI or VLMs in 2026 evals; only worth it if already AWS/GCP-committed.
- **Tesseract**: rejected as primary — acceptable only as a cheap triage pass (e.g., to
  detect "is this page text or blank").

Sources: [Reducto parser comparison](https://llms.reducto.ai/document-parser-comparison),
[opendataloader-bench rankings](https://pdfmux.com/blog/pdfmux-vs-llamaparse-vs-docling-vs-unstructured-2026/),
[Procycons PDF benchmark](https://procycons.com/en/blogs/pdf-data-extraction-benchmark/),
[Docling docs](https://docling-project.github.io/docling/),
[olmOCR 2](https://allenai.org/blog/olmocr-2), [Surya 2](https://github.com/datalab-to/surya),
[OCR guide 2026](https://slavadubrov.github.io/blog/2026/03/04/ocr-guide/),
[Azure DI layout](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout?view=doc-intel-4.0.0),
[Azure DI signature Q&A](https://learn.microsoft.com/en-za/answers/questions/5865436/signature-extraction-using-document-intelligence-o).

---

## 2. Chunking

### Recommendation

**Structural (layout-aware) parent-child chunking + Anthropic-style contextual
prepending**, with type-specific strategies:

| Doc type | Child chunk (embedded) | Parent (returned to LLM) | Overlap |
|---|---|---|---|
| Narrative SOP / protocol | 250-400 tokens, split on heading/paragraph boundaries from DoclingDocument | Full section (cap ~1,500-2,000 tokens); whole doc if < 2,000 | 0 at structural boundaries; 10-15% only for oversized flat sections |
| Excel FMEA / matrix | 1 row as key-value block with sheet name + full header row prepended (typically 100-300 tokens); merge tiny rows up to ~350 tokens | The row's worksheet region or the row + table summary | 0 |
| Any embedded table (in PDF/Word) | Table kept atomic if ≤ ~500 tokens; else row-group chunks with repeated headers | Whole table + preceding caption/paragraph | 0 |
| Scanned batch record | 1 page or 1 process step (whichever smaller), with record ID + step number in context | Page ± 1 page | n/a |
| Complaint form | Whole form if ≤ ~800 tokens; else per form section, preserving `field: value` pairs | Whole form | 0 |

Every child chunk gets a 50-100 token LLM-generated contextual preamble ("This chunk is
from SOP-023 rev C, 'Design Change Control', section 6.2 Verification, and describes...")
prepended before **both** dense embedding and sparse/BM25 indexing.

### Justification

- **Structural over fixed-size**: 2026 evaluations ("Reconstructing Context",
  adaptive-chunking work) consistently show structure-aligned chunking beats fixed-size on
  heterogeneous enterprise corpora; DoclingDocument gives you headings, tables, and lists
  for free, so fixed-size would throw away information you already paid to extract. SOPs
  are strongly sectioned — the section is the natural citation unit for an auditor.
- **Parent-child (small-to-big)**: small chunks embed precisely (better recall), large
  parents give the generator enough context to answer procedural questions without
  stitching. Store parents in Postgres keyed by `parent_id`; Qdrant holds only children.
- **Contextual retrieval**: Anthropic's numbers still hold up in 2026 revisits — 35%
  fewer retrieval failures with contextual embeddings, 49% with contextual BM25 too, 67%
  combined with reranking. Cost is one Haiku-class call per chunk with prompt caching
  (the full doc is cached; each chunk context costs little). At 50k docs / ~1-2M chunks
  this is a one-time indexing cost in the low hundreds of dollars — trivially justified
  for audit-grade recall. It also fixes the classic QMS failure mode: a chunk saying
  "the verification records shall be retained" is useless without knowing *which* SOP and
  *which* process it governs.
- **Excel rows with header context**: structure-aware tabular chunking research (STC,
  2026) confirms row-level key-value chunks with hierarchical header context beat
  linearized tables (up to 40-56% fewer chunks, fewer mid-record splits, better
  retrieval). For FMEA also index one table-level summary chunk (LLM-generated: scope,
  product, top risks) so "does the FMEA for product X consider failure mode Y?" can hit
  either level.
- **Forms**: preserving `field: value` structure keeps checkbox states and signature
  metadata queryable and keeps BM25 effective on field names.

### Alternatives considered

- **Late chunking (Jina)**: embeds the full doc then pools per-chunk — solves the same
  context-loss problem embedding-side only, requires a late-chunking-capable embedder,
  and does nothing for the BM25 index. Contextual prepending helps both dense and sparse
  and produces human-readable chunk context (useful in citations). Rejected as primary.
- **voyage-context-3** (Voyage's contextualized chunk embeddings): a genuinely cheaper
  alternative to LLM contextual prepending on the dense side (no LLM pass; document
  context baked into chunk vectors at embed time). Worth benchmarking as a
  cost-optimization later; still leaves sparse vectors context-free, so keep the LLM
  preamble for the hybrid index.
- **Semantic (embedding-similarity) chunking**: adds cost and nondeterminism; structural
  boundaries in QMS docs are better signals than embedding drift. Rejected.
- **Vision-guided chunking (ColPali-style page-image multivectors)**: strong for
  visually dense scanned content; Qdrant supports multivectors/maxSim, so this is a
  viable *additive* index for scanned batch records if text-OCR retrieval
  underperforms — noted as a phase-2 option, not the baseline.

Sources: [Anthropic contextual retrieval revisited](https://callsphere.ai/blog/vw6g-anthropic-contextual-retrieval-2026-revisit),
[Late chunking vs contextual retrieval](https://medium.com/kx-systems/late-chunking-vs-contextual-retrieval-the-math-behind-rags-context-problem-d5a26b9bbd38),
[Structure-aware tabular chunking](https://arxiv.org/pdf/2605.00318),
[Reconstructing Context](https://arxiv.org/pdf/2504.19754),
[Chunking strategies 2026](https://langcopilot.com/posts/2025-10-11-document-chunking-for-rag-practical-guide),
[Ragie table chunking](https://www.ragie.ai/blog/our-approach-to-table-chunking).

---

## 3. Embeddings

### Recommendation

**Voyage `voyage-4-large`**, 1024 dimensions, int8 quantization in Qdrant, **plus** Qdrant
BM25 sparse vectors on the same (contextualized) chunk text.

Verified specs (July 2026, Voyage docs):

| Model | Context | Dims (Matryoshka) | Price /M tokens | Notes |
|---|---|---|---|---|
| voyage-4-large | 32k | 256/512/**1024**/2048 | $0.12 | Best retrieval quality; MoE architecture; first 200M tokens free |
| voyage-4 | 32k | 256-2048 | $0.06 | ~Near-large quality, half price |
| voyage-4-lite | 32k | 256-2048 | $0.02 | Cheap tier |
| voyage-3-large / 3.5 | 32k | 256-2048 | $0.18 / $0.06 | Superseded by voyage-4 series |
| Cohere embed-v4 | 128k | 256/512/1024/1536 | ~$0.10-0.12 | Multimodal (text+image), strong multilingual |
| OpenAI text-embedding-3-large | 8k | MRL to 3072 | $0.13 | Older; safe default, no refresh since 2024 |
| Gemini Embedding 2 | large | MRL | ~$0.15 (Gemini-embedding-001 tier ~$0.006 batch on some routes) | Multimodal incl. audio; cheapest at volume via Google routes |

### Justification

- Voyage's 4-series leads current retrieval benchmarks (voyage-4-large reported +14%
  nDCG@10 vs text-embedding-3-large, +8% vs embed-v4 on Voyage's evals; independent
  roundups agree Voyage leads on domain-technical text, which regulatory/QMS language
  is). 32k context comfortably covers contextualized chunks; quantization-aware training
  means int8 in Qdrant costs almost nothing in quality and 4x less RAM; Matryoshka lets
  you drop to 512d later without re-embedding if latency/memory demands it.
- Cost sanity check: 50k docs × ~20k tokens avg = ~1B tokens ≈ $120 one-time at
  voyage-4-large (first 200M free). Embedding cost is a non-issue; pick on quality.
- Note Voyage is a MongoDB company — confirm enterprise DPA / zero-retention terms for
  QMS content (all four vendors offer zero-retention enterprise tiers).

**Sparse vectors: yes.** Audit queries are full of exact identifiers — "SOP-023",
"CAPA-2024-118", "UDI-DI", clause numbers ("ISO 13485 §7.3.7"), product codes. Dense
models are unreliable on these; BM25 is near-perfect. Use Qdrant's built-in BM25 sparse
vectors (server-side IDF) over the contextualized chunk text. miniCOIL (Qdrant's
context-aware sparse model) is an optional upgrade if BM25's term ambiguity shows up in
evals; SPLADE adds model inference cost at both index and query time for marginal gain on
this corpus profile — skip initially.

### Alternatives considered

- **Cohere embed-v4**: best pick *if* you embed page images (multimodal) or need heavy
  multilingual; 128k context irrelevant when chunks are small. Second choice.
- **OpenAI text-embedding-3-large**: unchanged since 2024; behind Voyage/Cohere on
  current retrieval benchmarks. Only pick for single-vendor simplicity.
- **voyage-law-2 / finance-2 domain models**: previous-generation; voyage-4-large now
  beats them broadly. No regulatory-specific model exists worth the fragmentation.
- **Self-hosted (bge-m3, gte, Qwen-embedding)**: viable for data-residency hardliners;
  bge-m3 conveniently emits dense+sparse+ColBERT. Accept ~5-10% quality drop and ops
  burden. Not needed since hosted APIs are allowed.

Sources: [Voyage embeddings docs](https://docs.voyageai.com/docs/embeddings),
[Voyage pricing](https://docs.voyageai.com/docs/pricing),
[Cohere embed docs](https://docs.cohere.com/docs/cohere-embed),
[Embedding comparison 2026](https://www.buildmvpfast.com/blog/best-embedding-model-comparison-voyage-openai-cohere-2026),
[Embedding specs table](https://pecollective.com/tools/text-embedding-models-compared/).

---

## 4. Hybrid search and fusion

### Recommendation

**Qdrant-native hybrid via the Universal Query API**: named vectors `dense`
(voyage-4-large, int8) + `sparse_bm25` per point; query with two `prefetch` branches
(dense limit ~100, sparse limit ~100) fused with **RRF**; do **not** deploy a separate
BM25 engine.

```python
client.query_points(
    collection,
    prefetch=[
        models.Prefetch(query=dense_vec, using="dense", limit=100, filter=acl_and_status_filter),
        models.Prefetch(query=sparse_vec, using="sparse_bm25", limit=100, filter=acl_and_status_filter),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=120,
)
```

### Justification

- **RRF over weighted-sum**: BM25 and cosine scores live on incompatible scales; RRF
  fuses on rank only, needs no tuning, and is the robust default across 2026 hybrid
  benchmarks. Qdrant also ships DBSF (distribution-based score fusion) natively — try it
  in evals; adopt only if it measurably wins. Hand-tuned weighted fusion is a
  maintenance liability (weights drift as the corpus changes) — only justified if evals
  show a persistent gap, and then implement client-side.
- **Qdrant sparse is enough at this scale**: server-side IDF/BM25, same filters and ACLs
  apply to both branches atomically, one system to operate, and 5k-50k docs (~1-2M
  chunks) is far below where a dedicated lexical engine differentiates. A separate
  OpenSearch/Elastic tier is warranted only for features Qdrant sparse lacks — phrase
  and proximity queries, custom analyzers/synonym graphs, aggregation-heavy enterprise
  search — none of which this app needs (exact-ID matching works fine with BM25
  tokenization plus a keyword payload index on `doc_id` for direct lookups).
- Use `group_by=parent_id` (or post-fusion dedup) so one long SOP section can't flood
  the candidate list before reranking.

Sources: [Qdrant hybrid search article](https://qdrant.tech/articles/hybrid-search/),
[Qdrant hybrid course + Query API](https://qdrant.tech/course/essentials/day-3/hybrid-search/),
[Qdrant sparse/BM25 demo](https://qdrant.tech/course/essentials/day-3/sparse-retrieval-demo/),
[Hybrid search reference 2026](https://www.digitalapplied.com/blog/hybrid-search-bm25-vector-reranking-reference-2026).

---

## 5. Reranking

### Recommendation

**Voyage `rerank-2.5`** as primary. Feed **100-120 fused candidates in**, take **top
12-15 out** (then expand to parents before generation). Inside agentic refinement loops
use `rerank-2.5-lite` with 50 in / 10 out.

### Justification

- Verified specs: rerank-2.5 / 2.5-lite have **32k-token context** per doc (vs 4,096 for
  Cohere rerank-v3.5), instruction-following ("prioritize the current effective
  revision"; "prefer documents about product X"), $0.05/M tokens ($0.02 lite) with 200M
  tokens free. Long context matters here: parent-expanded sections and FMEA row-groups
  blow past 4k tokens, and truncation at the reranker is a silent recall killer.
- Cross-encoder tradeoff: a rerank pass over 100 candidates adds ~300-600ms and
  dominates end-to-end retrieval quality (+10-20 nDCG points over fusion alone is
  typical; Anthropic's 67% failure-reduction figure requires the reranker). For a live
  audit chat, one reranked pass beats two unreranked retrieval loops on both latency and
  quality.
- Instruction-following rerankers double as a cheap relevance policy layer (recency,
  revision preference) without retraining anything.

### Alternatives considered

- **Cohere rerank-v4.0-pro / v4.0-fast** (released after 3.5; current Cohere lineup):
  strong, adds semi-structured/JSON reranking which is genuinely useful for FMEA
  row-records; benchmark head-to-head — on most English corpora Cohere/Voyage are within
  1-3 nDCG@10 points. A fine co-primary; pick per your eval set.
- **Jina reranker v2/v3**: open-weights, multilingual, good; mainly attractive
  self-hosted.
- **mxbai-rerank-large-v2**: strongest open-weights option if reranking must move
  on-prem; single-GPU deployable.
- **LLM-as-reranker (listwise via GPT/Claude/Gemini)**: highest ceiling, 10-50x cost and
  latency; unnecessary with modern cross-encoders. Rejected.

Sources: [Voyage reranker docs](https://docs.voyageai.com/docs/reranker),
[Voyage pricing](https://docs.voyageai.com/docs/pricing),
[Cohere rerank docs](https://docs.cohere.com/docs/rerank),
[Agentset reranker leaderboard](https://agentset.ai/rerankers),
[Reranker comparison](https://ianas.fr/en/).

---

## 6. Knowledge-graph RAG (Neo4j)

### Recommendation

**Schema-first, entity-centric KG built primarily from deterministic extraction of
document cross-references and registry metadata, with LLM extraction constrained to a
closed schema** — not Microsoft GraphRAG or LightRAG wholesale. Traversal from LangGraph
via **pre-canned parameterized Cypher tools**, with schema-constrained Text2Cypher as a
gated fallback. Graph results are joined back to Qdrant chunks by `doc_id` and reranked
together with vector results.

**Schema (starting point):**

- Nodes: `Document {doc_id, type, title, revision, status, effective_date}`,
  `Product`, `Process`, `FailureMode`, `RiskControl`, `CAPA`, `Complaint`,
  `Nonconformance`, `Requirement (e.g. ISO 13485 clause / 21 CFR 820 section)`, `Change`.
- Edges: `REFERENCES` (doc→doc, from explicit "per SOP-xxx" citations),
  `SUPERSEDES` (revision chain), `IMPLEMENTS` (doc→Requirement),
  `APPLIES_TO` (doc→Product/Process), `MITIGATED_BY` (FailureMode→RiskControl),
  `VERIFIED_BY` (RiskControl→Document), `TRIGGERED_BY` (CAPA→Complaint/NC),
  `AFFECTS` (Change→Document/Product).

**Extraction pipeline:** (1) regex/pattern extraction of document IDs, CAPA numbers,
clause citations from parsed text — deterministic, near-perfect precision on QMS
numbering conventions; (2) registry metadata (revision, status, product) from the
document control system or title blocks; (3) FMEA rows → FailureMode/RiskControl nodes
directly from the structured Excel extraction (no LLM needed); (4) an LLM pass **only**
for soft relations (e.g., IMPLEMENTS mapping to regulation clauses), emitting
strictly-validated schema instances with a source-chunk provenance property on every
edge.

**Traversal tools exposed to the agent** (each a typed LangGraph tool wrapping a fixed
parameterized Cypher template):
`get_document_graph(doc_id)`, `revision_history(doc_id)`,
`impacted_documents(doc_id | change_id)`, `trace_requirement(clause)`,
`capa_chain(capa_id | complaint_id)`, `risk_trace(product, failure_mode?)`.

### Justification

- **Why schema-first**: QMS corpora carry explicit, high-value structure (cross-
  references, revision chains, CAPA linkage, risk traceability). Deterministic extraction
  of that structure is cheap, verifiable, and — critically for audits — *defensible*:
  every edge has a provenance pointer to the sentence or cell that asserted it. Open LLM
  extraction (GraphRAG/LightRAG default mode) produces noisy, unvalidated entities;
  Neo4j's own analysis of LightRAG extraction shows significant duplication/drift. A
  wrong hop in an audit answer ("this complaint fed CAPA-118") is a worse failure than a
  missed retrieval.
- **Why not Microsoft GraphRAG**: its differentiator is Leiden community detection +
  hierarchical community summaries for *global sensemaking* ("summarize themes across
  the corpus"). Audit Q&A is dominated by local/multi-hop factual queries; community
  summarization is the expensive part (heavy LLM indexing cost) and mostly unused here.
  LightRAG's dual-level (entity/keyword local + graph global) retrieval at ~1/100th the
  indexing cost validates the lighter-weight direction, but both frameworks bring their
  own storage/orchestration; you already have LangGraph + Neo4j + Qdrant, so adopt the
  *pattern* (entity-anchored expansion), not the framework.
- **Why pre-canned traversals over free Text2Cypher**: deterministic tools are testable,
  fast, injection-proof, and produce reproducible answers (auditors may ask the same
  question twice). Text2CypherRetriever (neo4j-graphrag-python, first-party) is the
  right *fallback* for long-tail structural questions — run it against a read-only DB
  user, pass the explicit schema, validate generated Cypher (allowlist of labels/edge
  types, LIMIT enforcement), and route to it only when the router classifies a query as
  structural-but-uncovered.
- **Combining graph + vector**: two patterns, use both. (a) *Graph→vector*: traversal
  returns doc/entity IDs → filtered Qdrant retrieval (`doc_id in [...]`) pulls the
  actual text → single unified rerank. (b) *Vector→graph*: after normal retrieval,
  expand top hits' `doc_id`s one hop (REFERENCES/SUPERSEDES) and inject a compact
  structured context block ("SOP-023 rev C supersedes rev B (2024-03-02); referenced by
  WI-101, FRM-208") — cheap, high-value grounding for revision questions.

### Alternatives considered

- **Microsoft GraphRAG**: rejected as framework (cost, global-query focus); revisit
  community summaries only if "summarize across the QMS" queries become a real use case.
- **LightRAG**: right cost intuition, but open extraction + own storage abstractions;
  pattern adopted, framework not.
- **Graphiti (Zep)**: temporal KG focused on agent memory streams, not document
  traceability; not a fit.
- **No graph at all / Postgres-only**: see section 10 — genuinely viable at the low end
  of the corpus range and should be the fallback position if traceability queries turn
  out to be rare.

Sources: [Graph RAG in production 2026](https://www.paperclipped.de/en/blog/graph-rag-production/),
[Neo4j on LightRAG extraction](https://neo4j.com/blog/developer/under-the-covers-with-lightrag-extraction/),
[neo4j-graphrag-python docs](https://neo4j.com/docs/neo4j-graphrag-python/current/),
[Text2CypherRetriever](https://neo4j.com/blog/developer/effortless-rag-text2cypherretriever/),
[GraphRAG vs Neo4j roles](https://synapcores.com/blog/graphrag-vs-neo4j),
[GraphRAG vs vector RAG](https://www.buildmvpfast.com/blog/graphrag-vs-vector-rag-knowledge-graph-ai-2026).

---

## 7. Agentic retrieval in LangGraph

### Recommendation

**LangGraph 1.x `StateGraph`** (verified current: **1.2.9, released 2026-07-10,
production/stable, Python ≥3.10**) with this topology:

```
route → [decompose] → retrieve (parallel subgraphs) → grade → (rewrite ↺ ≤2) →
generate(cited) → verify_citations → (regenerate ↺ ≤1) → respond (streamed)
```

- **Router node**: classify query → `factual_lookup` (hybrid vector), `structural/
  multi-hop` (graph tools ± vector), `tabular/aggregate` (FMEA row retrieval or SQL over
  Postgres registry), `out_of_corpus` (refuse/escalate). Cheap structured-output call
  (Haiku/Flash-class).
- **Decomposition**: only for multi-part audit questions ("show the procedure, its
  latest revision, and any CAPAs referencing it") → sub-queries fan out via `Send` to
  parallel retrieval branches; results merged before grading.
- **Retrieval subgraphs**: one subgraph per tool family — `vector_tools` (hybrid
  search + rerank), `graph_tools` (section 6 traversals + gated Text2Cypher),
  `registry_tools` (Postgres SQL for metadata/status/date questions). Subgraphs keep
  tool families independently testable and their prompts/state isolated.
- **CRAG-style grading**: lightweight relevance grade of reranked context; on fail →
  one query rewrite (self-critique of why retrieval missed), bounded at 2 iterations —
  unbounded loops are a latency and cost hazard in a live audit. Use the *pattern*, not
  Self-RAG's fine-tuned reflection tokens (prompt-based reflection nodes get the benefit
  with zero training).
- **Citation grounding**: generator must emit claims with chunk-ID citations
  (structured output: `[{claim, chunk_ids}]` or inline markers). A **verify node** then
  checks every citation exists and entails its claim (fast LLM entailment over cited
  chunks only); failures trigger one regeneration with feedback, then honest hedging
  ("not found in the QMS"). Never ship an uncited claim to an auditor.
- **Persistence**: `PostgresSaver` from `langgraph-checkpoint-postgres` — thread per
  audit conversation, durable execution across process restarts, aligns with Postgres in
  the stack. Use `BaseStore` (Postgres-backed) only if cross-thread memory becomes a
  requirement.
- **Human-in-the-loop**: `interrupt()` + `Command(resume=...)` for escalation gates —
  e.g., pause before answering about open CAPAs or when the verify node fails twice, so
  a quality manager can approve/edit. This is LangGraph's first-class HITL mechanism in
  1.x and survives restarts via the checkpointer.
- **Streaming**: `stream_mode="messages"` for tokens + `custom` events for retrieval
  progress and citation payloads ("searching FMEAs… found 3 documents"); auditors
  tolerate latency far better with visible progress. (1.x also added per-node timeouts
  and node-level error handlers — set timeouts on every external-API node.)

### Justification

- **StateGraph over functional API**: both share the Pregel runtime/checkpointers, but
  the explicit graph gives a visualizable, auditable control flow (relevant when your
  RAG system itself may face software-validation scrutiny under the company's QMS),
  per-node retry/timeout policies, and easier partial re-execution. Use `@task`/
  `@entrypoint` only for small internal utilities.
- Router/grader/verifier as separate small-model nodes keeps cost down and each
  behavior independently evaluable (section 8 tests each node).

Sources: [langgraph on PyPI](https://pypi.org/project/langgraph/),
[LangGraph memory/persistence docs](https://docs.langchain.com/oss/python/langgraph/add-memory),
[langgraph-checkpoint-postgres](https://pypi.org/project/langgraph-checkpoint-postgres/),
[Self-reflective RAG with LangGraph](https://www.langchain.com/blog/agentic-rag-with-langgraph),
[Agentic RAG routing/grading/rewriting](https://sajalsharma.com/posts/comprehensive-agentic-rag/),
[Self-RAG and CRAG patterns](https://www.sotaaz.com/post/agentic-rag-part2-en).

---

## 8. Evaluation

### Recommendation

- **Golden dataset**: 150-300 QA pairs. Bootstrap synthetically (RAGAS
  `TestsetGenerator` or DeepEval `Synthesizer` over the parsed corpus), then
  human-curate every item; deliberately over-sample the hard classes — multi-hop
  traceability, FMEA row lookups, revision/date questions ("what was effective in March
  2024?"), checkbox/signature questions, and *unanswerable* questions (the system must
  refuse). Each item stores: question, reference answer, and **labeled evidence
  chunk/doc IDs**.
- **Retrieval metrics** (deterministic, no LLM judge, cheap): recall@5/10/20, MRR,
  nDCG@10 against labeled evidence IDs — computed directly (or via `ranx`) at two
  points: post-fusion and post-rerank, so regressions localize.
- **Generation metrics**: **DeepEval as the CI harness** (pytest-native pass/fail
  gates: faithfulness, answer relevancy, plus a custom G-Eval citation-accuracy metric =
  every cited chunk exists ∧ entails the claim ∧ no uncited factual claims). **RAGAS for
  offline tuning dashboards** — its `NoiseSensitivity` metric is uniquely valuable here
  (how much do distractor chunks corrupt answers — exactly the audit failure mode).
- **CI regression**: PR-gated smoke set (~30 questions, retrieval metrics + faithfulness
  gate, minutes and cents); nightly full run with trend tracking (LangSmith or
  Braintrust); re-run full eval on any index rebuild, embedding/reranker swap, or prompt
  change. Pin judge-model versions and set thresholds with a small tolerance band to
  damp judge variance.
- Also evaluate **nodes in isolation**: router classification accuracy, grader
  precision/recall, Text2Cypher validity rate — component evals catch regressions that
  end-to-end scores blur.

### Justification

The 2026 consensus is exactly this split: DeepEval's native idiom is red/green CI
assertions; RAGAS is dataset-level RAG analysis with a few metrics DeepEval lacks. Both
are cheap to run side-by-side off the same golden dataset. Deterministic retrieval
metrics in CI avoid judge-flakiness for the layer where determinism is available.

Alternatives: TruLens (OTel-native feedback functions — fine, weaker CI story),
Promptfoo (red-teaming focus; useful pre-launch adversarial pass), Arize Phoenix (open
observability + evals; good if avoiding LangSmith).

Sources: [DeepEval vs Ragas](https://deepeval.com/blog/deepeval-vs-ragas),
[Framework comparison](https://atlan.com/know/llm-evaluation-frameworks-compared/),
[DeepEval vs RAGAS 2026](https://genai.qa/blog/deepeval-vs-ragas/),
[RAG evaluation tools](https://aimultiple.com/rag-evaluation-tools).

---

## 9. Metadata design

### Recommendation

**Per-chunk payload (Qdrant) — Postgres remains the source of truth (document registry
table), payloads are a denormalized projection:**

```json
{
  "doc_id": "SOP-023",            // keyword, indexed
  "doc_type": "sop",              // keyword, indexed: sop|wi|fmea|batch_record|complaint|capa|protocol|report|form
  "title": "Design Change Control",
  "revision": "C",                // keyword, indexed
  "status": "effective",          // keyword, indexed: draft|effective|superseded|obsolete
  "effective_from": "2024-03-02T00:00:00Z",  // datetime, indexed
  "effective_to": null,           // datetime, indexed (null = still effective)
  "product_codes": ["PX-100"],    // keyword, indexed (array)
  "process_area": "design_controls", // keyword, indexed
  "owner_dept": "quality",        // keyword
  "section_path": "6.2 Verification",
  "page": 4,                      // integer, indexed
  "chunk_type": "narrative",      // keyword: narrative|table_row|table_summary|form_field|ocr_page
  "parent_id": "SOP-023-C#s6.2",  // keyword, indexed (parent fetch + group_by)
  "acl_groups": ["qa", "audit_room"], // keyword, indexed
  "ocr_confidence": 0.97,         // float (scanned docs only)
  "source_hash": "sha256:..."     // integrity/traceability
}
```

- **Create all payload indexes before bulk ingest** (keyword on doc_id, doc_type,
  status, revision, product_codes, acl_groups, parent_id, chunk_type; datetime on
  effective_from/effective_to; integer on page) and enable Qdrant's strict mode that
  **rejects filters on unindexed fields** — fail-fast beats silent full scans.
- **Effective-date modeling**: `effective_from`/`effective_to` ranges (not a single
  date) so "what was in force on date X" is one datetime range filter — a canonical
  audit question. Default retrieval filter is `status = effective`; the agent lifts it
  only when the router detects a historical question.
- **ACL pattern**: filter-based ACL — `acl_groups` must-match-any filter injected
  server-side by the retrieval service from the session principal, on **every** prefetch
  branch (never constructed by the LLM). Group-based, not per-user. Mirror the same
  authorization in Neo4j (node property/label filter inside each canned Cypher template)
  and Postgres (RLS on registry/parent-chunk tables) so no store leaks what another
  enforces. If the platform later serves multiple legal entities, use Qdrant
  multitenancy (`is_tenant: true` payload index) rather than per-tenant collections.

### Justification

These fields map one-to-one to how auditors scope questions (by procedure, product,
status, date, and record type) and to the chunking/graph design above (`parent_id`,
`chunk_type`). Qdrant docs are explicit that filterable fields must be payload-indexed
and indexed pre-ingest for performance; filter-based ACL is the standard pattern and
composes with hybrid prefetch. `source_hash` + `page` + `section_path` give every citation
an integrity-checkable provenance trail — the property that makes the system defensible
in an audit room.

Sources: [Qdrant indexing](https://qdrant.tech/documentation/manage-data/indexing/),
[Qdrant filtering](https://qdrant.tech/documentation/search/filtering/),
[Qdrant multitenancy](https://qdrant.tech/documentation/manage-data/multitenancy/),
[Qdrant 1.16 tiered multitenancy](https://qdrant.tech/blog/qdrant-1.16.x/).

---

## 10. Storage hypothesis review (Qdrant + Neo4j + Postgres)

- **Qdrant — keep.** Native hybrid (dense + BM25 sparse with server-side IDF) in one
  Query API call, payload-indexed filtering that composes with ACLs, quantization,
  multivector/ColPali option for a phase-2 visual index. No reason to reconsider at this
  scale.
- **Postgres — keep, and lean on it harder.** It is the natural home for four things
  beyond "storage": the document registry (source of truth for metadata payloads),
  parent-chunk store, LangGraph `PostgresSaver` checkpoints, and eval results/audit
  logs. (A pgvector-only stack would technically suffice at 5k docs, but Qdrant's hybrid
  + filtering maturity justifies itself well before 50k.)
- **Neo4j — justified only with the schema-first design; defer if in doubt.** This is
  the one component to re-examine. The graph's real payload here is a modest,
  well-typed set of relations (references, revisions, CAPA chains, risk traceability)
  extracted mostly deterministically. If early usage shows multi-hop traceability
  questions are <10-20% of audit queries, the same edges fit in Postgres tables with
  recursive CTEs at this corpus size, eliminating an entire database from the ops/
  validation surface. Recommended posture: build the extraction pipeline and canned
  "traversal tool" interface first (storage-agnostic), start with Postgres-backed edges,
  and promote to Neo4j when traversal depth/variety (variable-length paths, Text2Cypher
  fallback, graph algorithms) demonstrably outgrows SQL. If multi-hop traceability is a
  headline product feature, adopt Neo4j from day one — the schema above is ready either
  way.

---

## Recommended stack

| Layer | Primary choice | Key parameters | Fallback / alternative |
|---|---|---|---|
| Parsing (born-digital) | Docling (self-hosted) | DoclingDocument JSON; TableFormer tables; page+bbox provenance | LlamaParse; Reducto (premium) |
| Parsing (Excel/FMEA) | Native openpyxl row extraction | Row = key-value record + header context | Docling XLSX backend |
| OCR (scans) | Gemini 3 Flash (hosted VLM) | Checkbox → [x]/[ ]; signature-presence prompt; per-page confidence | olmOCR 2 / Surya 2 (self-hosted); Azure DI layout |
| Forms/signatures | VLM prompting or Azure DI custom neural | Presence + printed name/date only | — |
| Chunking | Structural parent-child + contextual prepending | Child 250-400 tok; parent ≤2k; FMEA row-level + headers; 50-100 tok context via Haiku-class + prompt caching | voyage-context-3 (dense-side alternative); late chunking |
| Embeddings | Voyage voyage-4-large | 1024-dim, int8, 32k ctx, $0.12/M | Cohere embed-v4 (multimodal); voyage-4 (cost) |
| Sparse | Qdrant built-in BM25 | Server-side IDF, over contextualized text | miniCOIL upgrade |
| Hybrid fusion | Qdrant Query API, RRF | 2 prefetch × 100 → fuse → 120; group_by parent | DBSF; client-side weighted (eval-driven only) |
| Reranker | Voyage rerank-2.5 | 100-120 in → 12-15 out; 32k ctx; instructions | Cohere rerank-v4.0-pro/fast; mxbai-rerank-v2 (self-host) |
| Knowledge graph | Schema-first KG in Neo4j (or Postgres edges initially) | Deterministic cross-ref extraction + schema-constrained LLM; provenance on every edge | LightRAG pattern; MS GraphRAG communities (only for global summarization) |
| Graph access | Pre-canned Cypher tools | revision_history, capa_chain, trace_requirement, impacted_documents | Gated Text2CypherRetriever (read-only, validated) |
| Orchestration | LangGraph 1.2.x StateGraph | route → decompose → parallel retrieve subgraphs → CRAG grade (≤2 loops) → cited generate → verify | Functional API for small subflows |
| Persistence/HITL | PostgresSaver + interrupt()/Command(resume) | Thread per audit conversation; escalation gates | — |
| Streaming | stream_mode="messages" + custom events | Progress + citation events | v3 event stream (experimental) |
| Evaluation | DeepEval (CI gates) + RAGAS (tuning) + ranx retrieval metrics | 150-300 curated QA; recall@k/MRR/nDCG@10 post-fusion and post-rerank; citation-entailment gate; nightly full + PR smoke | TruLens, Promptfoo (red team), Phoenix |
| Metadata/ACL | Qdrant indexed payloads, projection of Postgres registry | status+date defaults; effective_from/to ranges; acl_groups filter injected server-side; strict unindexed-filter rejection | Qdrant multitenancy if multi-entity |
