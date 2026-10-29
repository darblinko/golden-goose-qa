"""Retrieval settings enforce their numeric bounds at construction.

A misconfigured limit (a non-positive batch size, rerank_out larger than the
rerank_in window it draws from) is a deploy-time error, not a runtime surprise
mid-retrieval. Bounds are checked when the settings object is built so a bad
GG_RETRIEVAL_* value fails the process at startup with a clear message."""

import pytest
from gg_common.settings import RetrievalSettings
from pydantic import ValidationError


def test_defaults_are_within_bounds():
    settings = RetrievalSettings()
    assert settings.index_batch_size > 0
    assert settings.rerank_out <= settings.rerank_in


def test_index_batch_size_must_be_positive():
    with pytest.raises(ValidationError):
        RetrievalSettings(index_batch_size=0)


def test_prefetch_must_be_positive():
    with pytest.raises(ValidationError):
        RetrievalSettings(prefetch_dense=0)


def test_rerank_out_cannot_exceed_rerank_in():
    # You cannot rerank out more candidates than entered the reranker.
    with pytest.raises(ValidationError):
        RetrievalSettings(rerank_in=10, rerank_out=20)


def test_rerank_out_equal_to_rerank_in_is_allowed():
    settings = RetrievalSettings(rerank_in=12, rerank_out=12)
    assert settings.rerank_out == settings.rerank_in


def test_max_children_per_parent_may_be_zero_to_disable():
    assert RetrievalSettings(max_children_per_parent=0).max_children_per_parent == 0


def test_negative_max_children_per_parent_rejected():
    with pytest.raises(ValidationError):
        RetrievalSettings(max_children_per_parent=-1)


def test_negative_rerank_min_score_rejected():
    with pytest.raises(ValidationError):
        RetrievalSettings(rerank_min_score=-0.1)
