"""Reranker noise sensitivity: does injected off-topic evidence displace the
right documents?

Distractors are real chunks retrieved for *other* golden questions, so they
are fluent QMS text — the hardest realistic noise. The clean top-K candidates
plus distractors are reranked together; a robust reranker keeps recall flat
and lets few distractors into the final K. Runs entirely at the rerank layer,
so no store is mutated and the fake reranker exercises the same code path.
"""

from dataclasses import dataclass

from gg_retrieval.models import RetrievedChunk
from gg_retrieval.retriever import HybridRetriever

from gg_evals.metrics import recall_at_k
from gg_evals.retrieval_eval import (
    EvalItem,
    K,
    ranked_doc_keys,
    retrievable_evidence,
    select_items,
)

DISTRACTORS_PER_ITEM = 5


@dataclass(frozen=True)
class NoiseResult:
    item_id: str
    pattern: str
    recall_clean: float
    recall_noisy: float
    intrusion: float  # fraction of the noisy top-K occupied by distractors
    noise_tested: bool = True  # False when the item had no distractors to face


@dataclass(frozen=True)
class NoiseReport:
    results: tuple[NoiseResult, ...]

    @property
    def tested(self) -> tuple[NoiseResult, ...]:
        """Items that actually faced distractors. Degradation and intrusion are
        only meaningful here — an item with no distractor pool was not tested,
        and scoring its zero degradation as perfect robustness would let an
        empty noise set pass the gate."""
        return tuple(r for r in self.results if r.noise_tested)

    @property
    def recall_clean(self) -> float:
        return _mean([r.recall_clean for r in self.results])

    @property
    def recall_noisy(self) -> float:
        return _mean([r.recall_noisy for r in self.results])

    @property
    def degradation(self) -> float:
        """Mean recall lost to noise over noise-tested items; 0.0 = fully
        noise-robust. Untested items are excluded, not counted as perfect."""
        return _mean([r.recall_clean - r.recall_noisy for r in self.tested])

    @property
    def intrusion(self) -> float:
        return _mean([r.intrusion for r in self.tested])

    def as_dict(self) -> dict[str, object]:
        return {
            "n_items": len(self.results),
            "n_tested": len(self.tested),
            "recall_clean": round(self.recall_clean, 4),
            "recall_noisy": round(self.recall_noisy, 4),
            "degradation": round(self.degradation, 4),
            "intrusion": round(self.intrusion, 4),
        }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def pick_distractors(
    own: list[RetrievedChunk],
    pool: list[RetrievedChunk],
    relevant: set[str],
    *,
    count: int = DISTRACTORS_PER_ITEM,
) -> list[RetrievedChunk]:
    """Deterministic distractor choice: chunks from other questions whose
    document is neither relevant nor already among the item's own candidates,
    ordered by (doc_key, chunk_id) so runs are comparable across time."""
    own_ids = {c.chunk_id for c in own}
    own_docs = {c.doc_key for c in own}
    seen: set[str] = set()
    eligible = []
    for chunk in sorted(pool, key=lambda c: (c.doc_key, c.chunk_id)):
        if chunk.chunk_id in own_ids or chunk.chunk_id in seen:
            continue
        if chunk.doc_key in relevant or chunk.doc_key in own_docs:
            continue
        seen.add(chunk.chunk_id)
        eligible.append(chunk)
    return eligible[:count]


async def evaluate_noise(
    retriever: HybridRetriever, items: list[EvalItem], *, smoke_only: bool = False
) -> NoiseReport:
    selected, _ = select_items(items, smoke_only=smoke_only)

    clean: dict[str, list[RetrievedChunk]] = {}
    for item in selected:
        result = await retriever.retrieve(item.question, top_k=K)
        clean[item.id] = list(result.chunks)

    results = []
    for item in selected:
        own = clean[item.id]
        relevant_ids, _ = retrievable_evidence(item.evidence_doc_ids)
        relevant = set(relevant_ids)
        pool = [c for other_id, chunks in clean.items() if other_id != item.id for c in chunks]
        distractors = pick_distractors(own, pool, relevant)

        recall_clean = recall_at_k(ranked_doc_keys([c.doc_key for c in own]), relevant, K)
        if not own or not distractors:
            results.append(
                NoiseResult(
                    item_id=item.id,
                    pattern=item.pattern,
                    recall_clean=recall_clean,
                    recall_noisy=recall_clean,
                    intrusion=0.0,
                    noise_tested=False,
                )
            )
            continue

        candidates = own + distractors
        documents = [f"{c.context_header}\n\n{c.text}" for c in candidates]
        reranked = await retriever.reranker.rerank(item.question, documents, top_k=K)
        noisy_keys = ranked_doc_keys([candidates[r.index].doc_key for r in reranked])
        intruders = sum(1 for r in reranked if r.index >= len(own))
        results.append(
            NoiseResult(
                item_id=item.id,
                pattern=item.pattern,
                recall_clean=recall_clean,
                recall_noisy=recall_at_k(noisy_keys, relevant, K),
                intrusion=intruders / len(reranked) if reranked else 0.0,
            )
        )
    return NoiseReport(results=tuple(results))
