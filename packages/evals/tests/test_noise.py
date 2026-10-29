"""Reranker noise sensitivity: distractor selection and scoring."""

from typing import cast

from gg_common.providers.fakes import FakeRerankProvider
from gg_evals.noise import NoiseReport, NoiseResult, evaluate_noise, pick_distractors
from gg_evals.retrieval_eval import EvalItem
from gg_retrieval.models import RetrievalResult, RetrievedChunk
from gg_retrieval.retriever import HybridRetriever


def _chunk(chunk_id: str, doc_key: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_key=doc_key,
        doc_type="sop",
        title=doc_key,
        revision="A",
        section_path="1",
        text=text,
        context_header=f"{doc_key} Rev A",
        score=0.9,
        parent_id=None,
    )


def _item(item_id: str, question: str, evidence: list[str]) -> EvalItem:
    return EvalItem(
        id=item_id,
        question=question,
        pattern="procedure_content",
        evidence_doc_ids=evidence,
        smoke=True,
    )


CAPA_CHUNK = _chunk("c1", "SOP-004", "Corrective action effectiveness verification timeline.")
TRAIN_CHUNK = _chunk("c2", "SOP-013", "Training and competency requirements for inspectors.")


def test_pick_distractors_excludes_relevant_own_and_duplicates():
    own = [CAPA_CHUNK]
    pool = [
        TRAIN_CHUNK,
        TRAIN_CHUNK,  # duplicate chunk id from another question's retrieval
        _chunk("c3", "SOP-004", "Same document, different chunk."),  # own doc
        _chunk("c4", "SOP-006", "Complaint handling requirements."),  # relevant
        CAPA_CHUNK,  # own chunk id
    ]
    distractors = pick_distractors(own, pool, {"SOP-006"})
    assert [c.chunk_id for c in distractors] == ["c2"]


def test_pick_distractors_is_deterministic_and_capped():
    pool = [_chunk(f"c{i}", f"WI-{i:03d}", f"work instruction {i}") for i in range(9, 0, -1)]
    picked = pick_distractors([], pool, set(), count=3)
    assert [c.doc_key for c in picked] == ["WI-001", "WI-002", "WI-003"]


def test_report_means():
    report = NoiseReport(
        results=(
            NoiseResult("QA-1", "p", recall_clean=1.0, recall_noisy=0.5, intrusion=0.2),
            NoiseResult("QA-2", "p", recall_clean=1.0, recall_noisy=1.0, intrusion=0.0),
        )
    )
    assert report.degradation == 0.25
    assert report.intrusion == 0.1
    assert report.as_dict()["recall_noisy"] == 0.75


class StubNoiseRetriever:
    def __init__(self, by_question: dict[str, list[RetrievedChunk]]):
        self.by_question = by_question
        self.reranker = FakeRerankProvider()

    async def retrieve(self, query: str, *, top_k: int) -> RetrievalResult:
        return RetrievalResult(query=query, chunks=tuple(self.by_question[query]), parents=())


async def test_evaluate_noise_with_fake_reranker():
    items = [
        _item("QA-1", "What is the corrective action effectiveness timeline?", ["SOP-004"]),
        _item("QA-2", "What are the training competency requirements?", ["SOP-013"]),
    ]
    retriever = StubNoiseRetriever(
        {items[0].question: [CAPA_CHUNK], items[1].question: [TRAIN_CHUNK]}
    )
    report = await evaluate_noise(cast(HybridRetriever, retriever), items)
    assert len(report.results) == 2
    assert report.recall_clean == 1.0
    # The fake reranker weighs query-token overlap, so each question's own
    # document survives its cross-question distractor.
    assert report.recall_noisy == 1.0
    assert report.degradation == 0.0
    # One distractor among two candidates still occupies a top-K slot.
    assert report.intrusion == 0.5


async def test_single_item_has_no_distractor_pool():
    item = _item("QA-1", "What is the corrective action effectiveness timeline?", ["SOP-004"])
    retriever = StubNoiseRetriever({item.question: [CAPA_CHUNK]})
    report = await evaluate_noise(cast(HybridRetriever, retriever), [item])
    (result,) = report.results
    assert result.recall_noisy == result.recall_clean
    assert result.intrusion == 0.0
    # No distractor pool means the item was not actually noise-tested.
    assert result.noise_tested is False
    assert report.tested == ()


def test_untested_items_do_not_score_as_perfect_robustness():
    # A tested item that lost recall must not be masked by an untested item
    # reporting zero degradation. Degradation averages over tested items only.
    report = NoiseReport(
        results=(
            NoiseResult("QA-1", "p", recall_clean=1.0, recall_noisy=0.5, intrusion=0.4),
            NoiseResult(
                "QA-2", "p", recall_clean=1.0, recall_noisy=1.0, intrusion=0.0, noise_tested=False
            ),
        )
    )
    assert report.degradation == 0.5  # not diluted to 0.25 by the untested item
    assert report.intrusion == 0.4
    assert report.as_dict()["n_tested"] == 1
