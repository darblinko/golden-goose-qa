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


def test_role_block_dollar_tag_is_absent_from_the_password():
    # $$ in the password closed the DO block's $$ quote and broke the migration.
    baseline = _load_baseline()
    for password in ("abc$$def", "x$gg$y", "$gg$$gg1$"):
        statement = baseline._create_login_role_sql("gg_app", password)
        tag = statement.split("DO ", 1)[1].split()[0]
        assert tag.startswith("$") and tag.endswith("$")
        assert tag not in password
        assert statement.count(tag) == 2


def test_role_block_escapes_colons_for_text_binds():
    # op.execute wraps a string in text(), which reads ":word" as a bind param.
    baseline = _load_baseline()
    statement = baseline._create_login_role_sql("gg_app", "a:b")
    assert "'a\\:b'" in statement
