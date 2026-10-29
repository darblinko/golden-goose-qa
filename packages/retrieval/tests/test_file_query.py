"""File tool tests against real DuckDB with temp CSV, Parquet, and xlsx files.

Beyond the happy paths, these pin the sandbox properties: the guard only
admits the `data` table, and external access is disabled at the DuckDB level
so even SQL that slipped past the guard could not read other files.
"""

import duckdb
import openpyxl
import pytest
from gg_common.settings import AppSettings, ToolSettings
from gg_retrieval.tools.file_query import FileQueryError, _connect, describe_file, query_file
from gg_retrieval.tools.sqlguard import SqlGuardError

CSV_CONTENT = "part,qty,unit_cost\nlead-a,4,12.50\nlead-b,1,80.00\nheader,9,3.25\n"


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "parts.csv"
    path.write_text(CSV_CONTENT)
    return path


@pytest.fixture
def parquet_file(tmp_path, csv_file):
    path = tmp_path / "parts.parquet"
    connection = duckdb.connect(":memory:")
    # COPY ... TO does not accept a bind parameter for the target path.
    connection.execute(
        f"COPY (SELECT * FROM read_csv_auto('{csv_file}')) TO '{path}' (FORMAT PARQUET)"
    )
    connection.close()
    return path


@pytest.fixture
def xlsx_file(tmp_path):
    path = tmp_path / "parts.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["part", "qty", "unit_cost"])
    sheet.append(["lead-a", 4, 12.5])
    sheet.append(["lead-b", 1, 80.0])
    workbook.save(path)
    return path


@pytest.fixture
def settings():
    return AppSettings(tools=ToolSettings(file_row_limit=200))


class TestDescribe:
    def test_csv_columns_and_row_count(self, csv_file):
        result = describe_file(csv_file)
        assert result.tool == "file_query"
        assert "3 rows" in result.title
        assert [row["column"] for row in result.rows] == ["part", "qty", "unit_cost"]

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileQueryError, match="file not found"):
            describe_file(tmp_path / "absent.csv")

    def test_unsupported_suffix(self, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("hello")
        with pytest.raises(FileQueryError, match="unsupported file type"):
            describe_file(path)


class TestQuery:
    def test_csv_filter_and_aggregate(self, csv_file, settings):
        result = query_file(
            csv_file,
            "SELECT part, qty * unit_cost AS extended FROM data WHERE qty > 1 ORDER BY part",
            settings=settings,
        )
        assert result.columns == ("part", "extended")
        assert result.rows == (
            {"part": "header", "extended": 29.25},
            {"part": "lead-a", "extended": 50.0},
        )

    def test_parquet(self, parquet_file, settings):
        result = query_file(parquet_file, "SELECT count(*) AS n FROM data", settings=settings)
        assert result.rows == ({"n": 3},)

    def test_xlsx_types_survive(self, xlsx_file, settings):
        result = query_file(xlsx_file, "SELECT sum(qty) AS total_qty FROM data", settings=settings)
        assert result.rows == ({"total_qty": 5},)

    def test_row_limit_truncates(self, csv_file):
        settings = AppSettings(tools=ToolSettings(file_row_limit=1))
        result = query_file(csv_file, "SELECT part FROM data", settings=settings)
        assert result.truncated
        assert len(result.rows) == 1


class TestSandbox:
    def test_guard_only_admits_data_table(self, csv_file, settings):
        with pytest.raises(SqlGuardError, match="relation not allowed"):
            query_file(csv_file, "SELECT * FROM read_csv_auto('/etc/passwd')", settings=settings)

    def test_external_access_disabled_below_the_guard(self, csv_file):
        connection = _connect(csv_file)
        try:
            with pytest.raises(duckdb.Error):
                connection.execute(f"SELECT * FROM read_csv_auto('{csv_file}')")
        finally:
            connection.close()

    def test_settings_cannot_be_reenabled(self, csv_file):
        connection = _connect(csv_file)
        try:
            with pytest.raises(duckdb.Error):
                connection.execute("SET enable_external_access = true")
        finally:
            connection.close()
