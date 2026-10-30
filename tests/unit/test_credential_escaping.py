"""Database credentials with URL or conninfo metacharacters survive intact.

A password such as alpha@beta must not be split into a password and a host,
and spaces or quotes must not break the checkpointer's libpq conninfo."""

import pytest
from gg_common.settings import AppSettings, PostgresSettings
from goldengoose_api.main import _checkpointer_conninfo
from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr
from sqlalchemy.engine import make_url

_PASSWORDS = ["alpha@beta", "with space", "quo'te", 'dq"x', "p:a/s?s#w%rd"]


def _pg(password: str) -> PostgresSettings:
    return PostgresSettings(
        host="db.internal",
        port=6543,
        user="gg_app",
        password=SecretStr(password),
        admin_password=SecretStr(password),
        database="goldengoose",
    )


@pytest.mark.parametrize("password", _PASSWORDS)
@pytest.mark.parametrize("attribute", ["sqlalchemy_url", "admin_sqlalchemy_url"])
def test_sqlalchemy_urls_round_trip(attribute, password):
    url = make_url(getattr(_pg(password), attribute))
    assert url.password == password
    assert url.host == "db.internal"
    assert url.port == 6543
    assert url.database == "goldengoose"


@pytest.mark.parametrize("password", _PASSWORDS)
def test_libpq_dsn_round_trips(password):
    parsed = conninfo_to_dict(_pg(password).dsn)
    assert parsed["password"] == password
    assert parsed["host"] == "db.internal"
    assert parsed["port"] == "6543"
    assert parsed["dbname"] == "goldengoose"


@pytest.mark.parametrize("password", _PASSWORDS)
def test_checkpointer_conninfo_round_trips(password):
    parsed = conninfo_to_dict(_checkpointer_conninfo(AppSettings(postgres=_pg(password))))
    assert parsed["password"] == password
    assert parsed["host"] == "db.internal"
    assert parsed["user"] == "gg_app"
    assert parsed["options"] == "-c search_path=checkpoints"
