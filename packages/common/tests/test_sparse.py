from gg_common.sparse import (
    document_sparse_vector,
    query_sparse_vector,
    token_index,
    tokenize,
)


def test_tokenize_emits_compound_id_tokens():
    tokens = tokenize("Per SOP-004, the CAPA-2025-007 record was reviewed.")
    assert "sop-004" in tokens
    assert "capa-2025-007" in tokens
    # parts remain retrievable too
    assert "sop" in tokens
    assert "004" in tokens


def test_tokenize_drops_stopwords():
    tokens = tokenize("The device is in the field")
    assert "the" not in tokens
    assert "device" in tokens
    assert "field" in tokens


def test_document_vector_deterministic():
    text = "Corrective action per SOP-004 Rev C effectiveness check"
    assert document_sparse_vector(text) == document_sparse_vector(text)


def test_document_vector_sorted_unique_indices():
    vec = document_sparse_vector("sterilization validation sterilization records")
    assert list(vec.indices) == sorted(set(vec.indices))
    assert len(vec.indices) == len(vec.values)
    assert all(v > 0 for v in vec.values)


def test_bm25_tf_saturation():
    one = document_sparse_vector("sterilization")
    ten = document_sparse_vector(" ".join(["sterilization"] * 10))
    idx = token_index("sterilization")
    w1 = one.values[one.indices.index(idx)]
    w10 = ten.values[ten.indices.index(idx)]
    assert w10 > w1
    assert w10 < 10 * w1


def test_query_vector_unit_weights():
    vec = query_sparse_vector("What is the CAPA effectiveness check for SOP-004?")
    assert all(v == 1.0 for v in vec.values)
    assert token_index("sop-004") in vec.indices


def test_empty_text():
    assert document_sparse_vector("").indices == ()
    assert query_sparse_vector("the and of").indices == ()
