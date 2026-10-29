import pytest
from gg_evals.metrics import mrr_at_k, ndcg_at_k, recall_at_k


def test_recall_full_hit():
    assert recall_at_k(["A", "B", "C"], {"A", "C"}, 10) == 1.0


def test_recall_partial_and_cutoff():
    assert recall_at_k(["A", "X", "Y"], {"A", "C"}, 10) == 0.5
    assert recall_at_k(["X", "Y", "A"], {"A"}, 2) == 0.0


def test_recall_empty_relevant_rejected():
    with pytest.raises(ValueError):
        recall_at_k(["A"], set(), 10)


def test_mrr_positions():
    assert mrr_at_k(["A", "B"], {"A"}, 10) == 1.0
    assert mrr_at_k(["X", "A"], {"A"}, 10) == 0.5
    assert mrr_at_k(["X", "Y"], {"A"}, 10) == 0.0


def test_ndcg_perfect_and_late():
    assert ndcg_at_k(["A", "B"], {"A"}, 10) == 1.0
    late = ndcg_at_k(["X", "A"], {"A"}, 10)
    assert 0.0 < late < 1.0


def test_ndcg_ideal_normalization_with_many_relevant():
    # only 2 slots relevant can occupy in top-2; ideal must not divide by more
    assert ndcg_at_k(["A", "B"], {"A", "B", "C"}, 2) == 1.0


def test_duplicate_ranked_docs_do_not_inflate_recall():
    # A doc key repeated in the ranking must count once, not twice.
    assert recall_at_k(["A", "A"], {"A"}, 10) == 1.0
    assert recall_at_k(["A", "A", "B"], {"A", "B"}, 10) == 1.0


def test_duplicate_ranked_docs_do_not_inflate_ndcg():
    # ["A", "A"] vs {"A"} previously scored > 1.0 via double-counted DCG.
    assert ndcg_at_k(["A", "A"], {"A"}, 10) == 1.0


def test_dedupe_precedes_cutoff():
    # After first-occurrence dedupe, "A" holds rank 1, so the k=1 cutoff keeps it.
    assert recall_at_k(["A", "A", "B"], {"B"}, 1) == 0.0
    assert mrr_at_k(["A", "A", "B"], {"B"}, 2) == 0.5
