"""Ad-hoc tabular file analysis via DuckDB (CSV, Parquet, Excel).

The file is materialized into an in-memory DuckDB table named `data`, then
external access is disabled so guarded SQL can reach only that table — no
other files, no extensions, no attach. Excel loads through openpyxl (first
worksheet, first row as header) since core DuckDB has no xlsx reader.

Path authorization is the caller's responsibility; this module enforces
existence, a supported suffix, and the SQL guard.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import openpyxl
from gg_common.settings import AppSettings

from gg_retrieval.tools.models import ToolResult, plain_row
from gg_retrieval.tools.sqlguard import validate_select

SUPPORTED_SUFFIXES = (".csv", ".parquet", ".xlsx")
TABLE_NAME = "data"

_ALLOWED_RELATIONS = frozenset({TABLE_NAME})
_XLSX_TYPE_SNIFF_ROWS = 100


class FileQueryError(ValueError):
    """The file cannot be loaded for querying; the message says why."""


def describe_file(path: Path) -> ToolResult:
    connection = _connect(path)
    try:
        described = connection.execute(f"DESCRIBE {TABLE_NAME}").fetchall()
        total = connection.execute(f"SELECT count(*) FROM {TABLE_NAME}").fetchone()
        row_count = int(total[0]) if total else 0
    finally:
        connection.close()
    rows = tuple({"column": name, "type": column_type} for name, column_type, *_ in described)
    return ToolResult(
        tool="file_query",
        title=f"Structure of {path.name} ({row_count} rows)",
        source=f"file: {path.name}",
        query=f"describe_file({path.name})",
        columns=("column", "type"),
        rows=rows,
    )


def query_file(path: Path, sql: str, *, settings: AppSettings) -> ToolResult:
    validated = validate_select(sql, allowed_relations=_ALLOWED_RELATIONS)
    limit = settings.tools.file_row_limit
    wrapped = f"SELECT * FROM ({validated}) AS gg_guarded LIMIT {limit + 1}"

    connection = _connect(path)
    try:
        cursor = connection.execute(wrapped)
        columns = tuple(str(description[0]) for description in cursor.description or ())
        fetched = cursor.fetchall()
    finally:
        connection.close()

    truncated = len(fetched) > limit
    rows = tuple(plain_row(dict(zip(columns, values, strict=True))) for values in fetched[:limit])
    return ToolResult(
        tool="file_query",
        title=f"Query over {path.name}",
        source=f"file: {path.name}",
        query=validated,
        columns=columns,
        rows=rows,
        truncated=truncated,
    )


def _connect(path: Path) -> duckdb.DuckDBPyConnection:
    if not path.is_file():
        raise FileQueryError(f"file not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(SUPPORTED_SUFFIXES)
        raise FileQueryError(
            f"unsupported file type: {suffix or path.name} (supported: {supported})"
        )

    connection = duckdb.connect(":memory:")
    try:
        if suffix == ".csv":
            connection.execute(
                f"CREATE TABLE {TABLE_NAME} AS SELECT * FROM read_csv_auto(?)", [str(path)]
            )
        elif suffix == ".parquet":
            connection.execute(
                f"CREATE TABLE {TABLE_NAME} AS SELECT * FROM read_parquet(?)", [str(path)]
            )
        else:
            _load_xlsx(connection, path)
        connection.execute("SET enable_external_access = false")
    except duckdb.Error as exc:
        connection.close()
        raise FileQueryError(f"could not load {path.name}: {exc}") from exc
    except Exception:
        connection.close()
        raise
    return connection


def _load_xlsx(connection: duckdb.DuckDBPyConnection, path: Path) -> None:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        row_iterator = sheet.iter_rows(values_only=True)
        header = next(row_iterator, None)
        if header is None:
            raise FileQueryError(f"empty worksheet in {path.name}")
        names = _column_names(header)
        data_rows = list(row_iterator)
    finally:
        workbook.close()

    types = [_sniff_type(data_rows, index) for index in range(len(names))]
    columns = ", ".join(
        f'"{name}" {column_type}' for name, column_type in zip(names, types, strict=True)
    )
    connection.execute(f"CREATE TABLE {TABLE_NAME} ({columns})")
    if not data_rows:
        return
    placeholders = ", ".join("?" for _ in names)
    normalized = [_pad_row(row, len(names), types) for row in data_rows]
    connection.executemany(f"INSERT INTO {TABLE_NAME} VALUES ({placeholders})", normalized)


def _column_names(header: tuple[Any, ...]) -> list[str]:
    names: list[str] = []
    for index, value in enumerate(header, start=1):
        name = str(value).strip() if value not in (None, "") else f"column_{index}"
        name = name.replace('"', "")
        if name in names:
            name = f"{name}_{index}"
        names.append(name)
    return names


def _sniff_type(data_rows: list[tuple[Any, ...]], index: int) -> str:
    """Pick a column type from the first rows; VARCHAR when values disagree."""
    seen: set[str] = set()
    for row in data_rows[:_XLSX_TYPE_SNIFF_ROWS]:
        value = row[index] if index < len(row) else None
        if value is None:
            continue
        if isinstance(value, bool):
            seen.add("BOOLEAN")
        elif isinstance(value, int):
            seen.add("BIGINT")
        elif isinstance(value, float):
            seen.add("DOUBLE")
        elif isinstance(value, datetime | date):
            seen.add("TIMESTAMP")
        else:
            seen.add("VARCHAR")
    if seen == {"BIGINT"}:
        return "BIGINT"
    if seen <= {"BIGINT", "DOUBLE"} and seen:
        return "DOUBLE"
    if len(seen) == 1:
        return seen.pop()
    return "VARCHAR"


def _pad_row(row: tuple[Any, ...], width: int, types: list[str]) -> list[Any]:
    values: list[Any] = []
    for index in range(width):
        value = row[index] if index < len(row) else None
        if value is not None and types[index] == "VARCHAR" and not isinstance(value, str):
            value = str(value)
        values.append(value)
    return values
