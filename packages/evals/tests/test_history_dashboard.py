"""Eval history JSONL and the self-contained trend dashboard."""

from gg_evals.dashboard import metric_series, render_dashboard, sparkline
from gg_evals.history import (
    append_history,
    load_history,
    make_record,
    overwrite_history,
    prune_incomparable,
)


def _record(recall: float, grounded: float, schema_version: int | None = 2) -> dict:
    metrics = {
        "retrieval": {"recall@10": recall, "mrr@10": 0.8},
        "answers": {
            "grounded_rate": grounded,
            "citation_precision": 0.4,
            "citation_recall": 0.5,
            "support": 0.8,
        },
        "routing": {"accuracy": 1.0},
        "noise": {"degradation": 0.0, "intrusion": 0.01},
    }
    return make_record(metrics, smoke=True, git_sha="abc1234", schema_version=schema_version)


def test_history_roundtrip(tmp_path):
    path = tmp_path / "evals" / "history.jsonl"
    append_history(path, _record(0.85, 1.0))
    append_history(path, _record(0.9, 0.96))
    records = load_history(path)
    assert len(records) == 2
    assert records[0]["git_sha"] == "abc1234"
    assert records[0]["smoke"] is True
    assert records[1]["metrics"]["retrieval"]["recall@10"] == 0.9
    assert all("created_at" in r for r in records)


def test_load_history_missing_file_is_empty(tmp_path):
    assert load_history(tmp_path / "absent.jsonl") == []


def test_make_record_stamps_schema_version():
    assert _record(0.9, 1.0, schema_version=3)["schema_version"] == 3


def test_prune_incomparable_drops_records_from_a_different_schema():
    records = [_record(0.8, 1.0, schema_version=1), _record(0.9, 1.0, schema_version=2)]
    kept, dropped = prune_incomparable(records, schema_version=2)
    assert [r["metrics"]["retrieval"]["recall@10"] for r in kept] == [0.9]
    assert [r["metrics"]["retrieval"]["recall@10"] for r in dropped] == [0.8]


def test_prune_incomparable_drops_unstamped_records():
    # A pre-stamp run has no schema_version and cannot be compared.
    legacy = _record(0.8, 1.0, schema_version=None)
    kept, dropped = prune_incomparable([legacy], schema_version=2)
    assert kept == [] and dropped == [legacy]


def test_prune_incomparable_keeps_all_when_current_schema_is_unknown():
    records = [_record(0.8, 1.0, schema_version=1), _record(0.9, 1.0, schema_version=2)]
    kept, dropped = prune_incomparable(records, schema_version=None)
    assert kept == records and dropped == []


def test_overwrite_history_replaces_the_file(tmp_path):
    path = tmp_path / "history.jsonl"
    append_history(path, _record(0.5, 1.0))
    append_history(path, _record(0.6, 1.0))
    overwrite_history(path, [_record(0.9, 1.0)])
    records = load_history(path)
    assert len(records) == 1
    assert records[0]["metrics"]["retrieval"]["recall@10"] == 0.9


def test_metric_series_walks_dotted_paths():
    records = [_record(0.85, 1.0), _record(0.9, 0.96)]
    assert metric_series(records, "retrieval.recall@10") == [0.85, 0.9]
    assert metric_series(records, "answers.grounded_rate") == [1.0, 0.96]
    assert metric_series(records, "missing.path") == [None, None]


def test_sparkline_handles_flat_and_gapped_series():
    assert "<polyline" in sparkline([0.5, 0.5, 0.5])
    assert "<polyline" in sparkline([0.5, None, 0.9])
    assert sparkline([None, None]) == "<svg></svg>"


def test_dashboard_is_self_contained_html():
    html_text = render_dashboard([_record(0.85, 1.0), _record(0.9, 0.96)])
    assert "<svg" in html_text
    assert "Retrieval recall@10" in html_text
    assert "0.9000" in html_text  # latest recall value
    assert "abc1234" in html_text
    assert "QA schema 2" in html_text  # run stamped with its golden-set version
    # Self-contained: no external asset references.
    assert "http://" not in html_text and "https://" not in html_text
    assert "<script" not in html_text


def test_dashboard_renders_with_no_history():
    html_text = render_dashboard([])
    assert "0 runs" in html_text
