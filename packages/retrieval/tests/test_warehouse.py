"""Warehouse tool tests with a stub session recording every statement.

The stub verifies the execution contract — read-only transaction, LOCAL role
switch, timeout, LIMIT wrapping, rollback — without a live Postgres. The
saved-query catalogue itself must pass the same guard as ad-hoc SQL.
"""

from typing import cast

import pytest
from gg_common.settings import AppSettings, ToolSettings
from gg_retrieval.tools.sqlguard import SqlGuardError, validate_select
from gg_retrieval.tools.warehouse import (
    ALLOWED_RELATIONS,
    RESTRICTED_RELATIONS,
    SAVED_QUERIES,
    WarehouseTool,
    relations_for_role,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class StubResult:
    def __init__(self, rows):
        self.rows = rows

    def keys(self):
        return tuple(self.rows[0]) if self.rows else ()

    def mappings(self):
        return self

    def all(self):
        return self.rows


class StubSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []
        self.rolled_back = False
        self.fail = False

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, clause, params=None):
        if self.fail:
            raise RuntimeError("connection lost")
        sql = str(clause)
        self.statements.append((sql, params))
        if sql.startswith("SET"):
            return None
        return StubResult(self.rows)

    async def rollback(self):
        self.rolled_back = True


def make_tool(rows, *, sql_row_limit=200):
    session = StubSession(rows)
    settings = AppSettings(tools=ToolSettings(sql_row_limit=sql_row_limit))
    factory = cast(async_sessionmaker[AsyncSession], session)
    return WarehouseTool(session_factory=factory, settings=settings), session


class TestSavedQueries:
    def test_every_saved_query_passes_the_guard(self):
        for name, query in SAVED_QUERIES.items():
            validated = validate_select(query.sql, allowed_relations=ALLOWED_RELATIONS)
            assert validated == query.sql, name

    async def test_unknown_name_lists_available(self):
        tool, _ = make_tool([])
        with pytest.raises(LookupError, match="open_ncrs"):
            await tool.run_saved("nonexistent")

    async def test_missing_params_rejected(self):
        tool, session = make_tool([])
        with pytest.raises(SqlGuardError, match="doc_key"):
            await tool.run_saved("training_for_document")
        assert session.statements == []

    async def test_execution_contract(self):
        rows = [{"capa_id": "CAPA-2025-007", "effectiveness_due": None}]
        tool, session = make_tool(rows)
        result = await tool.run_saved("overdue_capa_effectiveness")

        executed = [sql for sql, _ in session.statements]
        assert executed[0] == "SET TRANSACTION READ ONLY"
        assert executed[1] == "SET LOCAL statement_timeout = 5000"
        assert executed[2] == "SELECT set_config('gg.read_restricted', :flag, true)"
        assert session.statements[2][1] == {"flag": "on"}  # default role is admin
        assert executed[3] == "SET LOCAL ROLE sql_tool_ro"
        assert executed[4].startswith("SELECT * FROM (")
        assert executed[4].endswith("LIMIT 201")
        assert session.rolled_back

        assert result.tool == "warehouse"
        assert result.source == "registers.v_capa_register"
        assert result.rows == (rows[0],)
        assert not result.truncated

    async def test_params_forwarded(self):
        tool, session = make_tool([])
        await tool.run_saved("training_for_document", {"doc_key": "SOP-004"})
        _, params = session.statements[-1]
        assert params == {"doc_key": "SOP-004"}


class TestAdHoc:
    async def test_guard_rejects_before_any_execution(self):
        tool, session = make_tool([])
        with pytest.raises(SqlGuardError, match="relation not allowed"):
            await tool.run_sql("SELECT * FROM registers.capa")
        assert session.statements == []

    async def test_truncation_flag(self):
        rows = [{"ncr_id": f"NCR-{i}"} for i in range(3)]
        tool, session = make_tool(rows, sql_row_limit=2)
        result = await tool.run_sql("SELECT ncr_id FROM registers.v_ncr_register")
        assert result.truncated
        assert len(result.rows) == 2
        assert session.statements[-1][0].endswith("LIMIT 3")

    async def test_rollback_even_on_execution_failure(self):
        tool, session = make_tool([])
        session.fail = True
        with pytest.raises(RuntimeError):
            await tool.run_sql("SELECT ncr_id FROM registers.v_ncr_register")
        assert session.rolled_back

    async def test_date_values_become_json_safe(self):
        from datetime import date

        rows = [{"ncr_id": "NCR-001", "opened": date(2025, 3, 1)}]
        tool, _ = make_tool(rows)
        result = await tool.run_sql("SELECT ncr_id, opened FROM registers.v_ncr_register")
        assert result.rows[0]["opened"] == "2025-03-01"


class TestRoleNarrowing:
    def test_privileged_roles_see_every_relation(self):
        assert relations_for_role("admin") == ALLOWED_RELATIONS
        assert relations_for_role("qa_user") == ALLOWED_RELATIONS

    def test_auditor_loses_restricted_relations(self):
        narrowed = relations_for_role("auditor_readonly")
        assert narrowed == ALLOWED_RELATIONS - RESTRICTED_RELATIONS
        assert "registers.v_complaint_register" not in narrowed
        assert "registers.v_mdr_register" not in narrowed

    def test_unknown_role_fails_closed(self):
        assert relations_for_role("intruder") == ALLOWED_RELATIONS - RESTRICTED_RELATIONS

    async def test_restricted_sql_rejected_before_execution(self):
        tool, session = make_tool([])
        with pytest.raises(SqlGuardError, match="relation not allowed"):
            await tool.run_sql(
                "SELECT complaint_id FROM registers.v_complaint_register",
                role="auditor_readonly",
            )
        assert session.statements == []

    async def test_restricted_saved_query_rejected_before_execution(self):
        tool, session = make_tool([])
        with pytest.raises(SqlGuardError, match="relation not allowed"):
            await tool.run_saved("complaints_without_risk_evaluation", role="auditor_readonly")
        assert session.statements == []

    async def test_auditor_query_on_general_relation_sets_guc_off(self):
        rows = [{"ncr_id": "NCR-001"}]
        tool, session = make_tool(rows)
        result = await tool.run_sql(
            "SELECT ncr_id FROM registers.v_ncr_register", role="auditor_readonly"
        )
        guc = [(sql, params) for sql, params in session.statements if "set_config" in sql]
        assert guc == [("SELECT set_config('gg.read_restricted', :flag, true)", {"flag": "off"})]
        assert result.rows == ({"ncr_id": "NCR-001"},)

    async def test_qa_user_keeps_restricted_access(self):
        rows = [{"complaint_id": "C-2025-0142"}]
        tool, session = make_tool(rows)
        await tool.run_saved("complaints_without_risk_evaluation", role="qa_user")
        guc = [params for sql, params in session.statements if "set_config" in sql]
        assert guc == [{"flag": "on"}]
