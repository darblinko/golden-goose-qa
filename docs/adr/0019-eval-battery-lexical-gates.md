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

## Implementation note (2026-10-28)
The decision text above is unchanged. The implementation differs from it in
five places:

1. Gate count. Lines 38 to 39 list five gates. `BatteryThresholds`
   (`packages/evals/src/gg_evals/battery.py` lines 38 to 49) and
   `gate_failures` (battery.py lines 84 to 92) apply seven metric gates: the
   five listed plus citation precision at least 0.5 and citation recall at
   least 0.5. battery.py lines 99 to 102 add an absolute non-leakage check,
   and battery.py lines 163 to 165 add the coverage floors defined in
   `packages/evals/src/gg_evals/invariants.py` lines 32 to 47.
2. Citation precision. Lines 41 to 42 state that citation precision is
   tracked and not gated. battery.py lines 46, 47, 88 and 89 gate citation
   precision and citation recall at 0.5; battery.py lines 42 to 45 mark both
   floors as provisional.
3. Noise metric. Lines 35 to 36 state that the noise eval gates on ndcg
   degradation. `NoiseReport.degradation`
   (`packages/evals/src/gg_evals/noise.py` lines 58 to 62) is the mean
   recall@10 lost to distractors over noise-tested items, and battery.py line
   91 gates that value at 0.15 or less.
4. Support scoring. Lines 22 to 24 state that each answer sentence is scored
   by its best coverage in any evidence text. `score_final_state`
   (`packages/evals/src/gg_evals/answer_eval.py` line 131) calls
   `cited_sentence_support` (`packages/evals/src/gg_evals/entailment.py`
   lines 107 to 123), which scores each sentence only against the sources its
   own [n] markers cite and uses the whole evidence window only for a
   sentence with no marker.
5. Calibration values. Lines 38 to 41 give calibration results (recall
   0.950, grounded 1.000, support 0.830, routing 1.000, degradation 0.000)
   without a revision or seed. No run output is recorded in the repository, and the revision and seed of the calibration run are not recorded.
