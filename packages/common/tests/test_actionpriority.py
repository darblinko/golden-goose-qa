"""Action Priority table loading, validation and lookup.

Every expected value here comes from the bundled synthetic example table, which
is not the AIAG-VDA table. No test depends on the handbook's values.
"""

import copy
import json
import logging
from pathlib import Path

import pytest
from gg_common import actionpriority
from gg_common.actionpriority import (
    SYNTHETIC_EXAMPLE_PATH,
    ActionPriorityTableError,
    compute_action_priority,
    configured_table,
    load_table,
)
from gg_common.settings import get_settings

EXAMPLE = load_table(SYNTHETIC_EXAMPLE_PATH)


def _example_raw() -> dict:
    return json.loads(SYNTHETIC_EXAMPLE_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, raw: object) -> Path:
    path = tmp_path / "ap.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.fixture
def fresh_config(monkeypatch):
    """Clear the cached settings and table around a test that sets GG_AP_TABLE_PATH."""
    get_settings.cache_clear()
    configured_table.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()
    configured_table.cache_clear()


def test_example_is_labelled_synthetic():
    assert EXAMPLE.synthetic is True
    assert "not the AIAG-VDA" in EXAMPLE.name


@pytest.mark.parametrize(
    ("severity", "occurrence", "detection", "expected"),
    [
        (10, 10, 10, "H"),
        (9, 4, 5, "H"),
        (9, 3, 4, "M"),
        (8, 3, 4, "L"),
        (8, 5, 5, "M"),
        (10, 2, 6, "M"),
        (10, 2, 7, "H"),
        (6, 10, 10, "H"),
        (5, 7, 6, "M"),
        (2, 2, 2, "L"),
        (1, 10, 10, "M"),
        (1, 1, 1, "L"),
    ],
)
def test_example_table_values(severity, occurrence, detection, expected):
    assert EXAMPLE.lookup(severity, occurrence, detection) == expected


def test_full_grid_covered_and_valid():
    letters = {
        EXAMPLE.lookup(s, o, d) for s in range(1, 11) for o in range(1, 11) for d in range(1, 11)
    }
    assert letters == {"H", "M", "L"}


def test_example_monotonic_within_axis():
    order = {"L": 0, "M": 1, "H": 2}
    for s in range(1, 11):
        for o in range(1, 11):
            for d in range(1, 11):
                here = order[EXAMPLE.lookup(s, o, d)]
                if d < 10:
                    assert order[EXAMPLE.lookup(s, o, d + 1)] >= here
                if o < 10:
                    assert order[EXAMPLE.lookup(s, o + 1, d)] >= here
                if s < 10:
                    assert order[EXAMPLE.lookup(s + 1, o, d)] >= here


@pytest.mark.parametrize("bad", [0, 11, -1, 100])
def test_out_of_range_inputs_raise(bad):
    with pytest.raises(ValueError):
        compute_action_priority(bad, 5, 5)
    with pytest.raises(ValueError):
        compute_action_priority(5, bad, 5)
    with pytest.raises(ValueError):
        compute_action_priority(5, 5, bad)


def test_unset_path_uses_synthetic_example_and_warns(fresh_config, caplog):
    fresh_config.delenv("GG_AP_TABLE_PATH", raising=False)
    with caplog.at_level(logging.WARNING, logger=actionpriority.__name__):
        table = configured_table()
    assert table == EXAMPLE
    assert "synthetic example" in caplog.text


def test_configured_path_is_loaded(fresh_config, tmp_path):
    raw = _example_raw()
    raw["name"] = "Site table"
    raw["synthetic"] = False
    raw["levels"] = [[["H"] * 5 for _ in range(5)] for _ in range(5)]
    fresh_config.setenv("GG_AP_TABLE_PATH", str(_write(tmp_path, raw)))
    assert configured_table().name == "Site table"
    assert compute_action_priority(1, 1, 1) == "H"


def test_configured_missing_file_raises(fresh_config, tmp_path):
    fresh_config.setenv("GG_AP_TABLE_PATH", str(tmp_path / "absent.json"))
    with pytest.raises(ActionPriorityTableError, match="cannot read"):
        configured_table()


def test_explicit_table_overrides_configuration():
    raw = _example_raw()
    raw["levels"] = [[["M"] * 5 for _ in range(5)] for _ in range(5)]
    table = actionpriority.parse_table(raw, source="inline")
    assert compute_action_priority(10, 10, 10, table=table) == "M"


def test_irregular_bands_are_supported(tmp_path):
    raw = {
        "name": "Two-band test table",
        "synthetic": True,
        "bands": {"severity": [5, 10], "occurrence": [3, 10], "detection": [10]},
        "levels": [[["L"], ["L"]], [["M"], ["H"]]],
    }
    table = load_table(_write(tmp_path, raw))
    assert table.lookup(5, 10, 1) == "L"
    assert table.lookup(6, 3, 1) == "M"
    assert table.lookup(6, 4, 10) == "H"


def _mutated(mutate) -> dict:
    raw = copy.deepcopy(_example_raw())
    mutate(raw)
    return raw


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r.pop("levels"), "missing key 'levels'"),
        (lambda r: r.pop("bands"), "missing key 'bands'"),
        (lambda r: r.update(name=""), "'name' must be a non-empty string"),
        (lambda r: r.update(synthetic="yes"), "'synthetic' must be true or false"),
        (lambda r: r["bands"].pop("detection"), "bands.detection"),
        (lambda r: r["bands"].update(severity=[2, 4, 4, 8, 10]), "strictly increasing"),
        (lambda r: r["bands"].update(severity=[2, 4, 6, 8, 9]), "end at 10"),
        (lambda r: r["bands"].update(severity=[0, 4, 6, 8, 10]), "between 1 and 10"),
        (lambda r: r["bands"].update(severity=[2.5, 4, 6, 8, 10]), "integers"),
        (lambda r: r["levels"].pop(), "levels must have 5 severity rows"),
        (lambda r: r["levels"][0].pop(), r"levels\[0\] must have 5 occurrence rows"),
        (lambda r: r["levels"][1][2].pop(), r"levels\[1\]\[2\] must have 5 detection"),
        (lambda r: r["levels"][3][3].__setitem__(0, "X"), "must be one of H, M, L"),
    ],
)
def test_invalid_tables_rejected(tmp_path, mutate, message):
    path = _write(tmp_path, _mutated(mutate))
    with pytest.raises(ActionPriorityTableError, match=message) as excinfo:
        load_table(path)
    assert str(path) in str(excinfo.value)


def test_non_json_file_rejected(tmp_path):
    path = tmp_path / "ap.json"
    path.write_text("S,O,D,AP\n", encoding="utf-8")
    with pytest.raises(ActionPriorityTableError, match="not valid JSON"):
        load_table(path)


def test_non_object_rejected(tmp_path):
    with pytest.raises(ActionPriorityTableError, match="JSON object"):
        load_table(_write(tmp_path, [1, 2, 3]))
