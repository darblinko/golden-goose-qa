"""The baseline migration builds two dynamic statements — CREATE ROLE ...
PASSWORD (a string literal) and GRANT ALL ON DATABASE (an identifier) — from
configuration. A password or database name carrying a quote must stay inside its
literal/identifier rather than break out into injectable SQL."""

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "infra" / "migrations" / "versions" / "0001_baseline.py"
)


def _load_baseline():
    spec = importlib.util.spec_from_file_location("baseline_0001_quoting", _MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sql_literal_escapes_embedded_quote():
    baseline = _load_baseline()
    assert baseline._sql_literal("pa'ss") == "'pa''ss'"
    assert baseline._sql_literal("plain") == "'plain'"


def test_sql_identifier_escapes_embedded_quote():
    baseline = _load_baseline()
    assert baseline._sql_identifier('db"x') == '"db""x"'
    assert baseline._sql_identifier("goldengoose") == '"goldengoose"'
