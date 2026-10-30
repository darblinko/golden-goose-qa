"""The as-of overdue effectiveness query evaluates on the question's date, not
on CURRENT_DATE, against the live seed-42 registers."""

from datetime import date

import pytest
from gg_common.settings import get_settings
from gg_retrieval.tools.warehouse import WarehouseTool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.integration


def _overdue_on(rows, as_of: date) -> set[str]:
    return {
        r.capa_id
        for r in rows
        if r.opened <= as_of
        and r.effectiveness_due is not None
        and r.effectiveness_due < as_of
        and (r.effectiveness_completed is None or r.effectiveness_completed > as_of)
    }


@pytest.mark.parametrize("as_of", [date(2025, 6, 1), date(2026, 1, 1), date(2026, 7, 1)])
async def test_as_of_overdue_matches_the_register_on_that_date(derived_corpus, app_engine, as_of):
    factory = async_sessionmaker(app_engine, expire_on_commit=False)
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT capa_id, opened, effectiveness_due, effectiveness_completed"
                    " FROM registers.v_capa_register"
                )
            )
        ).all()
    tool = WarehouseTool(session_factory=factory, settings=get_settings())
    result = await tool.run_saved("overdue_capa_effectiveness_as_of", {"as_of": as_of})
    assert {row["capa_id"] for row in result.rows} == _overdue_on(rows, as_of)
    if as_of == date(2026, 7, 1):
        # DEF-003: CAPA-2025-007 was due 2026-05-15 and never completed.
        assert "CAPA-2025-007" in {row["capa_id"] for row in result.rows}
