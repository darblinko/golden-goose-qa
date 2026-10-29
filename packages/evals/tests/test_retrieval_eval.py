from dataclasses import dataclass
from typing import cast

from gg_evals.retrieval_eval import (
    EvalItem,
    detect_leaks,
    evaluate,
    ranked_doc_keys,
    retrievable_evidence,
    select_items,
)
from gg_retrieval.retriever import HybridRetriever

ITEMS = [
    EvalItem(
        id="qa-001",
        question="What is the current revision of SOP-004?",
        pattern="revision_approval",
        evidence_doc_ids=["SOP-004"],
        smoke=True,
    ),
    EvalItem(
        id="qa-002",
        question="Which complaint led to MDR-0001?",
        pattern="complaint_mdr",
        evidence_doc_ids=["MDR-0001", "C-2024-0110"],
        smoke=True,
    ),
    EvalItem(
        id="qa-003",
        question="How many complaints were received in 2024?",
        pattern="counts_aggregates",
        evidence_doc_ids=["corpus:complaints:2024"],
        smoke=True,
    ),
    EvalItem(
        id="qa-004",
        question="Is Sarah trained to SOP-001?",
        pattern="training",
        evidence_doc_ids=["TRN-100", "SOP-001"],
        smoke=False,
    ),
]


def test_retrievable_evidence_filters_pseudo_ids():
    docs, reason = retrievable_evidence(["TM-100", "REQ-017"])
    assert docs == ["TM-100"]
    assert reason is None


def test_retrievable_evidence_all_excluded_gives_reason():
    docs, reason = retrievable_evidence(["corpus:capas:2024"])
    assert docs == []
    assert reason is not None and "warehouse" in reason


def test_select_items_smoke_and_skips():
    selected, skipped = select_items(ITEMS, smoke_only=True)
    assert [i.id for i in selected] == ["qa-001", "qa-002"]
    assert set(skipped) == {"qa-003"}


def test_select_items_keeps_training_matrix_evidence():
    """TRN-100 gained a parser in Phase 3, so it counts as retrievable evidence."""
    selected, _ = select_items(ITEMS, smoke_only=False)
    training = next(i for i in selected if i.id == "qa-004")
    docs, _ = retrievable_evidence(training.evidence_doc_ids)
    assert docs == ["TRN-100", "SOP-001"]


def test_ranked_doc_keys_dedup_preserves_first_rank():
    assert ranked_doc_keys(["A", "B", "A", "C", "B"]) == ["A", "B", "C"]


@dataclass(frozen=True)
class _StubChunk:
    doc_key: str
    revision: str | None = None


@dataclass(frozen=True)
class _StubResult:
    chunks: tuple[_StubChunk, ...]


class StubRetriever:
    def __init__(self, answers: dict[str, list[str]]):
        self.answers = answers

    async def retrieve(self, query: str, *, top_k: int):
        docs = self.answers.get(query, [])
        return _StubResult(chunks=tuple(_StubChunk(d) for d in docs))


def test_detect_leaks_flags_bare_document_key():
    chunks = [_StubChunk("SOP-004"), _StubChunk("SOP-006")]
    assert detect_leaks(chunks, ["SOP-006"]) == ("SOP-006",)
    assert detect_leaks(chunks, ["SOP-009"]) == ()


def test_detect_leaks_flags_exact_revision_only():
    # An obsolete revision must not surface; the current revision of the same
    # document is fine, so "@" matching must be revision-exact.
    chunks = [_StubChunk("SOP-004", revision="C")]
    assert detect_leaks(chunks, ["SOP-004@B"]) == ()  # B is not present
    assert detect_leaks(chunks, ["SOP-004@C"]) == ("SOP-004@C",)


def test_detect_leaks_revision_qualified_needs_revision_on_chunk():
    # A chunk without a revision attribute can never match a revision-qualified
    # exclusion — treated as absent, never a false leak.
    assert detect_leaks([_StubChunk("SOP-004")], ["SOP-004@B"]) == ()


def test_detect_leaks_empty_exclude_is_noop():
    assert detect_leaks([_StubChunk("SOP-004")], []) == ()


async def test_evaluate_flags_leak_and_reports_it():
    item = EvalItem(
        id="qa-leak",
        question="What does the SOP require?",
        pattern="procedure_content",
        evidence_doc_ids=["SOP-004"],
        must_exclude=["SOP-006"],
        smoke=True,
    )
    retriever = StubRetriever({item.question: ["SOP-004", "SOP-006"]})
    report = await evaluate(cast(HybridRetriever, retriever), [item], smoke_only=True)
    (result,) = report.results
    assert result.leaked == ("SOP-006",)
    # The leak is surfaced on the report and in its serialized form.
    assert report.leaks == (("qa-leak", ("SOP-006",)),)
    assert report.as_dict()["leaks"] == {"qa-leak": ["SOP-006"]}


async def test_evaluate_clean_run_has_no_leaks():
    item = EvalItem(
        id="qa-clean",
        question="What does the SOP require?",
        pattern="procedure_content",
        evidence_doc_ids=["SOP-004"],
        must_exclude=["SOP-006"],
        smoke=True,
    )
    retriever = StubRetriever({item.question: ["SOP-004"]})
    report = await evaluate(cast(HybridRetriever, retriever), [item], smoke_only=True)
    assert report.leaks == ()
    assert report.as_dict()["leaks"] == {}


async def test_evaluate_scores_and_skips():
    retriever = StubRetriever(
        {
            "What is the current revision of SOP-004?": ["SOP-004", "SOP-001"],
            "Which complaint led to MDR-0001?": ["MDR-0001", "SOP-006"],
        }
    )
    report = await evaluate(cast(HybridRetriever, retriever), ITEMS, smoke_only=True)
    assert len(report.results) == 2
    assert report.skipped == {
        "qa-003": (
            "corpus:complaints:2024: aggregate pseudo-id"
            " (answered by the record warehouse, not retrieval)"
        )
    }
    by_id = {r.item_id: r for r in report.results}
    assert by_id["qa-001"].recall == 1.0
    assert by_id["qa-002"].recall == 0.5  # C-2024-0110 missing from top-10
    assert report.recall == 0.75
    patterns = report.by_pattern()
    assert patterns["revision_approval"]["recall"] == 1.0
    assert patterns["complaint_mdr"]["recall"] == 0.5
