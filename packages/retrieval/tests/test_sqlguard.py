"""Guard tests: everything the agent could plausibly author, good and hostile.

The guard must reject anything it cannot positively account for — these
tests pin both the accepted shapes and the specific refusal reasons.
"""

import pytest
from gg_retrieval.tools.sqlguard import SqlGuardError, validate_select

ALLOWED = frozenset({"registers.v_ncr_register", "registers.v_capa_register"})


class TestAccepted:
    def test_simple_select(self):
        sql = "SELECT ncr_id, status FROM registers.v_ncr_register WHERE is_open"
        assert validate_select(sql, allowed_relations=ALLOWED) == sql

    def test_trailing_semicolon_stripped(self):
        sql = "SELECT count(*) FROM registers.v_ncr_register;"
        assert validate_select(sql, allowed_relations=ALLOWED) == sql.rstrip(";")

    def test_with_cte(self):
        sql = (
            "WITH open_items AS (SELECT capa_id FROM registers.v_capa_register WHERE is_open) "
            "SELECT count(*) FROM open_items"
        )
        assert validate_select(sql, allowed_relations=ALLOWED) == sql

    def test_union_of_allowed_views(self):
        sql = (
            "SELECT ncr_id AS id FROM registers.v_ncr_register "
            "UNION ALL SELECT capa_id FROM registers.v_capa_register"
        )
        assert validate_select(sql, allowed_relations=ALLOWED) == sql

    def test_explicit_join(self):
        sql = (
            "SELECT n.ncr_id, c.status FROM registers.v_ncr_register n "
            "JOIN registers.v_capa_register c ON c.capa_id = n.capa_id"
        )
        assert validate_select(sql, allowed_relations=ALLOWED) == sql

    def test_bind_parameters_pass(self):
        sql = "SELECT ncr_id FROM registers.v_ncr_register WHERE supplier_id = :supplier_id"
        assert validate_select(sql, allowed_relations=ALLOWED) == sql

    def test_keywords_inside_string_literals_ignored(self):
        sql = "SELECT ncr_id FROM registers.v_ncr_register WHERE description = 'drop table users'"
        assert validate_select(sql, allowed_relations=ALLOWED) == sql

    def test_quoted_identifier_column(self):
        sql = 'SELECT "Set Point" FROM data'
        assert validate_select(sql, allowed_relations=frozenset({"data"})) == sql

    def test_allowlisted_functions_pass(self):
        sql = (
            "SELECT status, count(*) AS n, min(opened), max(age_days), "
            "coalesce(sum(CASE WHEN is_open THEN 1 ELSE 0 END), 0), "
            "date_trunc('month', opened), extract(year FROM opened), lower(status) "
            "FROM registers.v_capa_register WHERE opened >= '2025-01-01' AND NOT is_open "
            "GROUP BY status, opened"
        )
        assert validate_select(sql, allowed_relations=ALLOWED) == sql


class TestRejected:
    @pytest.mark.parametrize(
        ("sql", "reason"),
        [
            ("", "empty"),
            ("SELECT 1; SELECT 2", "multiple SQL statements"),
            ("SELECT 1 -- sneak", "comments"),
            ("SELECT /* sneak */ 1", "comments"),
            ("EXPLAIN SELECT 1", "only SELECT"),
            ("INSERT INTO registers.v_ncr_register VALUES (1)", "only SELECT"),
            ("SELECT 1 FROM registers.v_ncr_register FOR UPDATE", "forbidden keyword: UPDATE"),
            ("SELECT pg_sleep(10) FROM registers.v_ncr_register", "function not allowed"),
            ("SELECT * FROM registers.ncr", "relation not allowed"),
            ("SELECT * FROM pg_catalog.pg_tables", "relation not allowed"),
            ("SELECT * FROM unnest(:ids)", "relation not allowed"),
            ("SELECT * FROM read_csv_auto('/etc/passwd')", "relation not allowed"),
            (
                "SELECT set_config('x', 'y', false) FROM registers.v_ncr_register",
                "function not allowed",
            ),
            ("SELECT $$sneak$$", "dollar-quoting"),
            ("SELECT 'unbalanced", "unbalanced"),
            ("SELECT do FROM registers.v_ncr_register", "forbidden keyword: DO"),
        ],
    )
    def test_rejects(self, sql, reason):
        with pytest.raises(SqlGuardError, match=reason):
            validate_select(sql, allowed_relations=ALLOWED)

    @pytest.mark.parametrize(
        "sql",
        [
            'SELECT "pg_sleep"(1) FROM registers.v_ncr_register',
            'SELECT "pg_catalog"."pg_sleep"(1) FROM registers.v_ncr_register',
            "SELECT pg_catalog.set_config('gg.read_restricted', 'on', true)",
            "SELECT \"set_config\"('gg.read_restricted', 'on', true)",
            "SELECT \"SET_CONFIG\"('gg.read_restricted', 'on', true)",
            "SELECT \"query_to_xml\"('SELECT * FROM registers.complaint', true, true, '')",
            "SELECT current_setting('gg.read_restricted') FROM registers.v_ncr_register",
            "SELECT generate_series(1, 1000000000) FROM registers.v_ncr_register",
            "SELECT ncr_id FROM registers.v_ncr_register WHERE \"lo_import\"('/etc/passwd') > 0",
        ],
    )
    def test_rejects_functions_outside_allowlist(self, sql):
        with pytest.raises(SqlGuardError, match="function not allowed"):
            validate_select(sql, allowed_relations=ALLOWED)

    def test_rejects_comma_join_smuggling(self):
        sql = "SELECT * FROM registers.v_ncr_register, pg_catalog.pg_tables"
        with pytest.raises(SqlGuardError, match="comma-separated FROM"):
            validate_select(sql, allowed_relations=ALLOWED)

    def test_rejects_quoted_relation(self):
        sql = 'SELECT * FROM "registers"."ncr"'
        with pytest.raises(SqlGuardError, match="relation not allowed"):
            validate_select(sql, allowed_relations=ALLOWED)

    def test_comma_inside_subquery_is_fine(self):
        sql = "SELECT * FROM (SELECT ncr_id, status FROM registers.v_ncr_register) AS open_items"
        assert validate_select(sql, allowed_relations=ALLOWED) == sql
