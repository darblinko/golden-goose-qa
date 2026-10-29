"""Rank metrics over retrieved document lists.

Implemented directly (recall/MRR/NDCG are a few lines each) rather than
pulling in ranx, whose numba dependency is heavyweight and fragile on new
Python versions. Inputs are ranked doc-key lists and relevant-doc sets.
"""

import math


def _unique_top_k(ranked: list[str], k: int) -> list[str]:
    """First-occurrence dedupe, then the top-k cutoff.

    A duplicated doc key must not be scored twice — otherwise recall for
    ``["A", "A"]`` against ``{"A"}`` is 2.0 and nDCG exceeds 1.0. Dedupe
    matches the retrieval harness (ranked_doc_keys), so live runs are
    unaffected; only pathological duplicate rankings are corrected here.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for doc in ranked:
        if doc not in seen:
            seen.add(doc)
            unique.append(doc)
    return unique[:k]


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        raise ValueError("relevant set must not be empty")
    hits = len(set(_unique_top_k(ranked, k)) & relevant)
    return hits / len(relevant)


def mrr_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    for position, doc in enumerate(_unique_top_k(ranked, k), start=1):
        if doc in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    dcg = sum(
        1.0 / math.log2(position + 1)
        for position, doc in enumerate(_unique_top_k(ranked, k), start=1)
        if doc in relevant
    )
    ideal = sum(1.0 / math.log2(position + 1) for position in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0
