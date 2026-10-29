"""Pure CLI helpers (the battery itself runs in integration tests)."""

import json

from gg_evals.cli import load_schema_version


def test_load_schema_version_reads_the_qa_set_field(tmp_path):
    path = tmp_path / "golden_qa.json"
    path.write_text(json.dumps({"schema_version": 2, "items": []}))
    assert load_schema_version(path) == 2


def test_load_schema_version_is_none_when_absent(tmp_path):
    path = tmp_path / "golden_qa.json"
    path.write_text(json.dumps({"items": []}))
    assert load_schema_version(path) is None


def test_load_schema_version_is_none_for_a_bare_list(tmp_path):
    path = tmp_path / "golden_qa.json"
    path.write_text(json.dumps([{"id": "QA-1"}]))
    assert load_schema_version(path) is None
