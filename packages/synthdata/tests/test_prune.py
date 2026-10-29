"""Stale-file pruning on regenerate (unit — the full generate path is covered
by the heavyweight fixture in test_generation.py)."""

from gg_synthdata.cli import _prune_stale


def _manifest(*paths: str) -> dict:
    return {"files": [{"path": p} for p in paths]}


def test_prune_removes_files_absent_from_the_manifest(tmp_path):
    (tmp_path / "corpus").mkdir()
    keep = tmp_path / "corpus" / "SOP-001.docx"
    keep.write_text("keep")
    stale = tmp_path / "corpus" / "OLD-999.docx"
    stale.write_text("stale from a prior run")
    (tmp_path / "manifest.json").write_text("{}")

    pruned = _prune_stale(tmp_path, _manifest("corpus/SOP-001.docx"))

    assert pruned == ["corpus/OLD-999.docx"]
    assert keep.exists()
    assert not stale.exists()
    assert (tmp_path / "manifest.json").exists()  # the manifest is never pruned


def test_prune_removes_now_empty_directories(tmp_path):
    (tmp_path / "corpus" / "scanned").mkdir(parents=True)
    (tmp_path / "corpus" / "scanned" / "old.png").write_text("x")

    _prune_stale(tmp_path, _manifest())

    assert not (tmp_path / "corpus" / "scanned").exists()


def test_prune_leaves_a_clean_snapshot_untouched(tmp_path):
    (tmp_path / "corpus").mkdir()
    kept = tmp_path / "corpus" / "SOP-001.docx"
    kept.write_text("keep")

    assert _prune_stale(tmp_path, _manifest("corpus/SOP-001.docx")) == []
    assert kept.exists()
