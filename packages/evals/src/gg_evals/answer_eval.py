"""End-to-end answer eval: run golden questions through the full agent graph
and score verdicts, citations, and evidence support.

Citation precision/recall compare cited doc keys against golden evidence;
support (see entailment.py) scores each answer sentence against the source its
own [n] markers cite, so citing the wrong document lowers support even when the
right document sits elsewhere in the window. Citation and support metrics
average over grounded answers only — an insufficient_evidence verdict has no
citations to score and is already penalized once through grounded_rate.

Task checks compare the answer against the golden answer where the task has a
single checkable fact. A counts_aggregates item is answered from the record
warehouse, has no document evidence, and is correct only when a grounded answer
states the golden count. These items enter grounded_rate and correctness but
not the citation and support means, which need golden documents.
"""

import re
from dataclasses import dataclass
from typing import Any, cast

from gg_agents.nodes import generation_parents
from gg_agents.prompts import source_excerpt
from gg_agents.state import AgentState, initial_state

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
    correct: bool | None = None  # None when the item has no task check
    document_evidence: bool = True


_COUNT_PATTERN = "counts_aggregates"
_LEADING_COUNT_RE = re.compile(r"^\s*(\d[\d,]*)\b")
_MARKER_RE = re.compile(r"\[\d+\]")
# A standalone integer: not part of a decimal (1.9), an identifier
# (CAPA-2025-009), a date (14-Mar-2025) or a word.
_STANDALONE_INT_RE = re.compile(
    r"(?<![\w.\-/])\d{1,3}(?:,\d{3})+(?![\w\-/]|\.\d)|(?<![\w.,\-/])\d+(?![\w,\-/]|\.\d)"
)


def expected_count(item: EvalItem) -> int | None:
    """The count a counts_aggregates golden answer states first, e.g. 17 in
    "17 CAPAs were opened in 2025."; None for any other item."""
    if item.pattern != _COUNT_PATTERN:
        return None
    match = _LEADING_COUNT_RE.match(item.answer)
    return int(match.group(1).replace(",", "")) if match else None


def answer_correct(item: EvalItem, state: dict[str, Any]) -> bool | None:
    expected = expected_count(item)
    if expected is None:
        return None
    if state.get("verdict") != "grounded":
        return False
    structured = _tool_count(state.get("parents") or [])
    if structured is not None and structured != expected:
        return False
    return stated_counts(item.question, state.get("answer") or "") == {expected}


def _integers(text: str) -> set[int]:
    return {int(n.replace(",", "")) for n in _STANDALONE_INT_RE.findall(text)}


def stated_counts(question: str, answer: str) -> set[int]:
    """The counts an answer asserts: its standalone integers, less citation
    markers and numbers the question itself carries (a year). A correct answer
    asserts exactly one count."""
    return _integers(_MARKER_RE.sub(" ", answer)) - _integers(question)


def _tool_count(parents: list[dict[str, Any]]) -> int | None:
    """The single integer cell of a one-row, one-column tool table, the shape
    a warehouse count returns; None for any other evidence."""
    if not parents or parents[0].get("doc_type") != "tool_result":
        return None
    lines = parents[0].get("text", "").splitlines()
    body = lines[2:] if len(lines) > 1 and lines[1].startswith("Source:") else []
    if len(body) != 2 or " | " in body[0] or not body[1].strip().isdigit():
        return None
    return int(body[1].strip())


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

    def checked(self) -> tuple[AnswerResult, ...]:
        return tuple(r for r in self.results if r.correct is not None)

    @property
    def correctness(self) -> float:
        checked = self.checked()
        return sum(1 for r in checked if r.correct) / len(checked) if checked else 0.0

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
            "n_checked": len(self.checked()),
            "correctness": round(self.correctness, 4),
            "incorrect": [
                {"item_id": r.item_id, "pattern": r.pattern}
                for r in self.checked()
                if not r.correct
            ],
            "ungrounded": [
                {"item_id": r.item_id, "pattern": r.pattern, "verdict": r.verdict}
                for r in self.ungrounded()
            ],
        }


def _grounded_mean(results: tuple[AnswerResult, ...], value: Any) -> float:
    grounded = [value(r) for r in results if r.grounded and r.document_evidence]
    return sum(grounded) / len(grounded) if grounded else 0.0


def _evidence_texts(state: dict[str, Any]) -> list[str]:
    """The generator's evidence window, numbered and rendered exactly as the
    prompt shows it (nodes.generation_parents, prompts.source_excerpt): support
    must be judged against what the model was actually shown."""
    window = cast(
        AgentState,
        {
            "parents": state.get("parents") or [],
            "external_parents": state.get("external_parents") or [],
        },
    )
    return [source_excerpt(parent) for parent in generation_parents(window)]


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
    golden, no_documents = retrievable_evidence(item.evidence_doc_ids)
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
        correct=answer_correct(item, state),
        document_evidence=no_documents is None,
    )


def select_answer_items(
    items: list[EvalItem], *, smoke_only: bool
) -> tuple[list[EvalItem], dict[str, str]]:
    """Retrieval-scorable items plus the warehouse items a task check can score."""
    selected, skipped = select_items(items, smoke_only=smoke_only)
    checkable = {i.id for i in items if i.id in skipped and expected_count(i) is not None}
    kept_ids = {i.id for i in selected} | checkable
    kept = [item for item in items if item.id in kept_ids]
    return kept, {item_id: why for item_id, why in skipped.items() if item_id not in checkable}


async def evaluate_answers(
    graph: Any, items: list[EvalItem], *, smoke_only: bool = False
) -> AnswerReport:
    """graph is a compiled agent graph (build_agent_graph without a
    checkpointer — eval turns are independent, never conversational)."""
    selected, skipped = select_answer_items(items, smoke_only=smoke_only)
    results = []
    for item in selected:
        final = await graph.ainvoke(initial_state(item.question))
        results.append(score_final_state(item, final))
    return AnswerReport(results=tuple(results), skipped=skipped)
