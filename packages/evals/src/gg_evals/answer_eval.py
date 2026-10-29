"""End-to-end answer eval: run golden questions through the full agent graph
and score verdicts, citations, and evidence support.

Citation precision/recall compare cited doc keys against golden evidence;
support (see entailment.py) scores each answer sentence against the source its
own [n] markers cite, so citing the wrong document lowers support even when the
right document sits elsewhere in the window. Citation and support metrics
average over grounded answers only — an insufficient_evidence verdict has no
citations to score and is already penalized once through grounded_rate.
"""

from dataclasses import dataclass
from typing import Any

from gg_agents.nodes import GENERATION_PARENTS
from gg_agents.state import initial_state

from gg_evals.entailment import cited_sentence_support
from gg_evals.retrieval_eval import EvalItem, retrievable_evidence, select_items


@dataclass(frozen=True)
class AnswerResult:
    item_id: str
    pattern: str
    verdict: str
    grounded: bool
    citation_precision: float
    citation_recall: float
    support: float


@dataclass(frozen=True)
class AnswerReport:
    results: tuple[AnswerResult, ...]
    skipped: dict[str, str]

    @property
    def grounded_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.grounded) / len(self.results)

    @property
    def citation_precision(self) -> float:
        return _grounded_mean(self.results, lambda r: r.citation_precision)

    @property
    def citation_recall(self) -> float:
        return _grounded_mean(self.results, lambda r: r.citation_recall)

    @property
    def support(self) -> float:
        return _grounded_mean(self.results, lambda r: r.support)

    def ungrounded(self) -> tuple[AnswerResult, ...]:
        return tuple(r for r in self.results if not r.grounded)

    def as_dict(self) -> dict[str, object]:
        return {
            "n_items": len(self.results),
            "n_skipped": len(self.skipped),
            "grounded_rate": round(self.grounded_rate, 4),
            "citation_precision": round(self.citation_precision, 4),
            "citation_recall": round(self.citation_recall, 4),
            "support": round(self.support, 4),
            "ungrounded": [
                {"item_id": r.item_id, "pattern": r.pattern, "verdict": r.verdict}
                for r in self.ungrounded()
            ],
        }


def _grounded_mean(results: tuple[AnswerResult, ...], value: Any) -> float:
    grounded = [value(r) for r in results if r.grounded]
    return sum(grounded) / len(grounded) if grounded else 0.0


def _evidence_texts(state: dict[str, Any]) -> list[str]:
    """Mirror of the generator's evidence window (nodes._generation_parents):
    support must be judged against what the model was actually shown."""
    parents = state.get("parents") or []
    external = state.get("external_parents") or []
    return [p["text"] for p in parents[:GENERATION_PARENTS] + external]


def _citation_scores(
    citations: list[dict[str, Any]], golden: list[str], evidence_revisions: dict[str, str]
) -> tuple[float, float]:
    """Citation precision and recall against the golden evidence keys. With
    evidence_revisions, a citation to the right document but the wrong revision
    is not a hit — an audit answer that cites an obsolete revision of the correct
    document is still wrong. Empty evidence_revisions scores at doc-key
    granularity, exactly as before."""
    golden_set = set(golden)
    if not evidence_revisions:
        cited = {c["doc_key"] for c in citations}
        hit = len(cited & golden_set)
        precision = hit / len(cited) if cited else 0.0
        recall = hit / len(golden_set) if golden_set else 0.0
        return precision, recall
    cited_pairs = {(c["doc_key"], c.get("revision")) for c in citations}
    cited_keys = {doc_key for doc_key, _ in cited_pairs}

    def revision_ok(doc_key: str) -> bool:
        expected = evidence_revisions.get(doc_key)
        return any(
            dk == doc_key and (expected is None or rev == expected) for dk, rev in cited_pairs
        )

    hit_keys = {k for k in cited_keys if k in golden_set and revision_ok(k)}
    precision = len(hit_keys) / len(cited_keys) if cited_keys else 0.0
    recall = len(hit_keys) / len(golden_set) if golden_set else 0.0
    return precision, recall


def score_final_state(item: EvalItem, state: dict[str, Any]) -> AnswerResult:
    verdict = state.get("verdict", "")
    grounded = verdict == "grounded"
    golden, _ = retrievable_evidence(item.evidence_doc_ids)
    precision, recall = _citation_scores(
        state.get("citations") or [], golden, item.evidence_revisions
    )
    return AnswerResult(
        item_id=item.id,
        pattern=item.pattern,
        verdict=verdict,
        grounded=grounded,
        citation_precision=precision,
        citation_recall=recall,
        support=cited_sentence_support(state.get("answer", ""), _evidence_texts(state)),
    )


async def evaluate_answers(
    graph: Any, items: list[EvalItem], *, smoke_only: bool = False
) -> AnswerReport:
    """graph is a compiled agent graph (build_agent_graph without a
    checkpointer — eval turns are independent, never conversational)."""
    selected, skipped = select_items(items, smoke_only=smoke_only)
    results = []
    for item in selected:
        final = await graph.ainvoke(initial_state(item.question))
        results.append(score_final_state(item, final))
    return AnswerReport(results=tuple(results), skipped=skipped)
