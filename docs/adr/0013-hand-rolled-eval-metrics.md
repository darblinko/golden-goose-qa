# ADR 0013: Hand-rolled ranking metrics instead of ranx

Status: accepted (2026-07-18)

## Context
The architecture named ranx for recall/MRR/nDCG. ranx depends on numba, and
numba/llvmlite wheels lag new CPython releases; on Python 3.13 the install
was fragile in this workspace. The metrics we gate on are small, well-known
formulas over lists of ids — not worth a JIT compiler dependency.

## Decision
`gg_evals.metrics` implements recall@k, MRR, and nDCG@k directly (49 lines),
with unit tests asserting known-answer values, including the tie and
missing-id edge cases. The eval harness and CI smoke gate consume these.

## Consequences
- No native-compilation dependency in the eval path; evals run anywhere the
  workspace installs.
- We forgo ranx's statistical significance testing and run comparison
  utilities; if Phase 6 tuning needs paired significance tests, ranx (or
  scipy) can be added to the evals package alone at that point.
- The formulas are frozen by unit tests against hand-computed values, so a
  refactor cannot silently change the gate's meaning.
