import pytest
from gg_common.objectstore import LocalObjectStore


def test_put_get_exists_list(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put("docs", "sop/SOP-001.pdf", b"content")
    assert store.exists("docs", "sop/SOP-001.pdf")
    assert store.get("docs", "sop/SOP-001.pdf") == b"content"
    assert not store.exists("docs", "sop/missing.pdf")
    store.put("docs", "sop/SOP-002.pdf", b"more")
    store.put("docs", "capa/CAPA-001.pdf", b"x")
    assert store.list_keys("docs", prefix="sop/") == ["sop/SOP-001.pdf", "sop/SOP-002.pdf"]
    assert store.list_keys("empty-bucket") == []


def test_path_traversal_rejected(tmp_path):
    store = LocalObjectStore(tmp_path)
    with pytest.raises(ValueError, match="escapes store root"):
        store.put("docs", "../../etc/passwd", b"nope")
