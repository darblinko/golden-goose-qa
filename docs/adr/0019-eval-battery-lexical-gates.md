# ADR 0019: Nightly eval battery with lexical entailment and calibrated gates

Status: accepted (2026-07-18)

## Context
Retrieval recall alone (ADR 0013) does not catch a system that retrieves
well and then answers badly: fabricated sentences, citations pointing at the
wrong documents, questions routed to the wrong tool, or a reranker that
collapses under near-duplicate distractors. Standard answer-quality
frameworks (RAGAS-style) use an LLM judge, which is nondeterministic,
costs money nightly, and is meaningless in keyless environments where the
generator itself is a deterministic fake.

## Decision
One gated battery (`gg-eval battery`) runs four evals over the golden QA
set, sharing a single fleet setup and forcing external tools offline for
determinism:

- Retrieval: recall/mrr/ndcg@10 (unchanged from ADR 0013).
- End-to-end answers: each question runs through the real agent graph;
  grounded rate from the verifier verdict, citation precision/recall
  against golden evidence doc ids, and sentence support — a lexical
  entailment proxy that scores each answer sentence by its best content-token
  coverage in any evidence text. This is a deliberate deviation from
  LLM-judge frameworks: it is deterministic, free, identical keyed and
  keyless, and fabrications lower coverage either way. It measures surface
  support, not semantic entailment; a paraphrasing generator scores lower
  than it deserves, so the gate is set at 0.5, not 0.8.
- Deterministic routing: `route_override` accuracy against per-pattern
  acceptable-route sets. Under fake providers this layer IS the runtime
  router, so it gates at 0.9. Acceptable sets were widened only where the
  target tool genuinely answers the question (verified against the graph and
  warehouse), never to make the number pass.
- Reranker noise: each question's candidate set is polluted with
  cross-question distractor chunks and reranked; gates on ndcg degradation
  and tracks distractor intrusion.

Gates (recall ≥ 0.8, grounded ≥ 0.8, support ≥ 0.5, routing ≥ 0.9,
degradation ≤ 0.15) were locked after calibrating live against the full
golden set (recall 0.950, grounded 1.000, support 0.830, routing 1.000,
degradation 0.000). Citation precision is tracked but not gated: the fake
generator cites every shown parent, and golden evidence sets are small.

A nightly workflow rebuilds the corpus from seed, ingests, derives, runs the
battery, and appends to a JSONL history rendered as a self-contained HTML
trend dashboard. History and dashboard are written before the gate decision
so failing nights still land in the trend.

## Consequences
- Quality regressions in retrieval, generation grounding, routing, or
  reranking fail CI within a day, with a trend line for slow drift.
- Lexical support is a floor, not a ceiling; when real providers are the
  nightly target, an LLM-judge eval can be added beside it without replacing
  the deterministic gate.
- The battery reuses the app's own dependency assembly; a change to agent
  wiring that breaks the battery build is itself a caught regression.
