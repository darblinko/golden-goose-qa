# ADR 0016: Deterministic tool routing ahead of the LLM router

Status: accepted (2026-07-18)

## Context
Some audit questions are structurally unambiguous: a question naming
CAPA-2024-001 is a record lookup, "how many complaints were received in
2024" is a warehouse count, a question naming REQ-017 is a trace walk.
Routing these through the LLM adds latency, cost, and a failure mode
(mis-routing under prompt drift) for zero benefit — and keyless deployments
running on fake providers would lose tool answers entirely.

## Decision
A regex layer (`gg_agents.toolselect`) runs before the LLM router:

- `route_override` maps high-precision patterns (record ids, REQ ids, count
  phrasing, training + document key) straight to the trace / aggregate /
  record patterns; anything it does not match falls through to the LLM
  router unchanged.
- `warehouse_plan` and `graph_plan` deterministically choose a saved query,
  bounded count SQL, or graph traversal for the routed question.
- Tool output re-enters the existing pipeline as a synthetic parent chunk
  (`tool_parent_dict`), so generation, verification, and citations treat a
  tool table exactly like a retrieved document section — one citation
  machinery, no parallel path.
- A tool failure ends the turn honestly: verdict `insufficient_evidence`
  with the reason in the answer, never a fallback to hallucination.

## Consequences
- The golden count, trace, and defect-discovery questions are answered
  identically with or without real provider keys, which is what the
  integration acceptance suite pins.
- The regexes are pinned to golden QA phrasings by unit tests; extending
  coverage means adding a pattern plus tests, not re-prompting a router.
- Questions the layer cannot classify still get the LLM router's judgment,
  so deterministic routing narrows model dependence without capping
  capability.
