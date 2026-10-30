"""The baseline role statement keeps an awkward password intact when run
through text(), the way op.execute runs it. The role can then log in."""

import importlib.util
from pathlib import Path

import psycopg
import pytest
from gg_common.settings import get_settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "infra" / "migrations" / "versions" / "0001_baseline.py"
)
_ROLE = "gg_quote_probe"


def _baseline():
    spec = importlib.util.spec_from_file_location("baseline_0001_probe", _MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("password", ["abc$$def", "it's:a 100% $tag$ test"])
async def test_awkward_password_creates_a_working_login(admin_engine: AsyncEngine, password):
    statement = _baseline()._create_login_role_sql(_ROLE, password)
    async with admin_engine.begin() as conn:
        await conn.execute(text(f"DROP ROLE IF EXISTS {_ROLE}"))
        await conn.execute(text(statement))
    try:
        pg = get_settings().postgres
        with psycopg.connect(
            host=pg.host, port=pg.port, dbname=pg.database, user=_ROLE, password=password
        ) as probe:
            assert probe.execute("SELECT current_user").fetchone() == (_ROLE,)
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(text(f"DROP ROLE IF EXISTS {_ROLE}"))
