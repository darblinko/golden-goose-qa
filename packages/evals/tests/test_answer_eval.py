"""Answer eval scoring against synthetic final states and a stub graph."""

from typing import Any

from gg_evals.answer_eval import evaluate_answers, score_final_state
from gg_evals.retrieval_eval import EvalItem

ITEM = EvalItem(
    id="QA-1",
    question="What does SOP-004 require for effectiveness verification?",
    pattern="procedure_content",
    evidence_doc_ids=["SOP-004", "SOP-006"],
    smoke=True,
)

EVIDENCE_TEXT = "Effectiveness verification is required within 90 days of CAPA closure."

GROUNDED_STATE: dict[str, Any] = {
    "verdict": "grounded",
    "answer": "Effectiveness verification is required within 90 days of closure. [1]",
    "citations": [{"doc_key": "SOP-004"}, {"doc_key": "WI-020"}],
    "parents": [{"text": EVIDENCE_TEXT}],
    "external_parents": [],
}


def test_grounded_state_scores_citations_and_support():
    result = score_final_state(ITEM, GROUNDED_STATE)
    assert result.grounded
    assert result.citation_precision == 0.5  # SOP-004 golden, WI-020 not
    assert result.citation_recall == 0.5  # SOP-006 never cited
    assert result.support == 1.0


def test_ungrounded_state_scores_zero_citations():
    state: dict[str, Any] = {
        "verdict": "insufficient_evidence",
        "answer": "",
        "citations": [],
        "parents": [],
        "external_parents": [],
    }
    result = score_final_state(ITEM, state)
    assert not result.grounded
    assert result.citation_precision == 0.0
    assert result.citation_recall == 0.0


def test_external_evidence_counts_toward_support():
    state = dict(GROUNDED_STATE) | {
        "parents": [],
        "external_parents": [{"text": EVIDENCE_TEXT}],
    }
    assert score_final_state(ITEM, state).support == 1.0


def test_exact_revision_citation_counts_only_matching_revision():
    # With expected revisions, a citation to the right document at the wrong
    # revision is not a hit — an obsolete revision of the correct SOP is still
    # a wrong answer for an audit.
    item = EvalItem(
        id="QA-REV",
        question="What is the current effectiveness rule?",
        pattern="procedure_content",
        evidence_doc_ids=["SOP-004"],
        evidence_revisions={"SOP-004": "C"},
        smoke=True,
    )
    wrong_rev = dict(GROUNDED_STATE) | {"citations": [{"doc_key": "SOP-004", "revision": "B"}]}
    right_rev = dict(GROUNDED_STATE) | {"citations": [{"doc_key": "SOP-004", "revision": "C"}]}
    assert score_final_state(item, wrong_rev).citation_precision == 0.0
    assert score_final_state(item, wrong_rev).citation_recall == 0.0
    assert score_final_state(item, right_rev).citation_precision == 1.0
    assert score_final_state(item, right_rev).citation_recall == 1.0


def test_missing_expected_revision_falls_back_to_doc_key_match():
    # A doc listed in evidence_revisions without an expected value still scores
    # at doc-key granularity for that key — any revision of it is a hit.
    item = EvalItem(
        id="QA-REV2",
        question="q",
        pattern="procedure_content",
        evidence_doc_ids=["SOP-004"],
        evidence_revisions={"SOP-006": "A"},  # a different doc carries the constraint
        smoke=True,
    )
    state = dict(GROUNDED_STATE) | {"citations": [{"doc_key": "SOP-004", "revision": "B"}]}
    assert score_final_state(item, state).citation_precision == 1.0
    assert score_final_state(item, state).citation_recall == 1.0


class StubGraph:
    def __init__(self, states: dict[str, dict[str, Any]]):
        self.states = states

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.states[state["question"]]


async def test_evaluate_answers_aggregates_and_skips_unretrievable():
    other = EvalItem(
        id="QA-2",
        question="How many CAPAs are open?",
        pattern="counts_aggregates",
        evidence_doc_ids=["corpus:capa-register"],
        smoke=True,
    )
    ungroundable = EvalItem(
        id="QA-3",
        question="What color is the cleanroom door?",
        pattern="procedure_content",
        evidence_doc_ids=["SOP-004"],
        smoke=True,
    )
    graph = StubGraph(
        {
            ITEM.question: GROUNDED_STATE,
            ungroundable.question: {"verdict": "insufficient_evidence", "answer": ""},
        }
    )
    report = await evaluate_answers(graph, [ITEM, other, ungroundable])
    assert report.grounded_rate == 0.5
    assert "QA-2" in report.skipped  # aggregate pseudo-id is unretrievable
    # Citation and support means cover grounded answers only.
    assert report.citation_precision == 0.5
    assert report.support == 1.0
    assert [r.item_id for r in report.ungrounded()] == ["QA-3"]


async def test_empty_report_is_all_zero():
    report = await evaluate_answers(StubGraph({}), [])
    assert report.grounded_rate == 0.0
    assert report.support == 0.0


def test_support_ignores_revisionless_controlled_document():
    # The generator drops a controlled document without a revision before it
    # numbers the sources, so [1] in the answer points at the revised SOP. The
    # eval must score against that same window, not the raw parent list.
    unrevised = {
        "provenance": "internal",
        "doc_type": "sop",
        "revision": None,
        "text": EVIDENCE_TEXT,
        "citation": "SOP-004",
    }
    revised = {
        "provenance": "internal",
        "doc_type": "sop",
        "revision": "B",
        "text": "Training records are retained for ten years.",
        "citation": "SOP-006 Rev B",
    }
    state = dict(GROUNDED_STATE) | {"parents": [unrevised, revised]}
    assert score_final_state(ITEM, state).support == 0.0


def test_support_uses_the_rendered_excerpt():
    # A long parent is clipped to the context budget before the generator sees
    # it; a sentence supported only by the clipped tail was not in the evidence.
    long_text = "Unrelated preamble about document control. " * 200 + EVIDENCE_TEXT
    state = dict(GROUNDED_STATE) | {"parents": [{"text": long_text}]}
    assert score_final_state(ITEM, state).support == 0.0
