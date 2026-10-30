"""Validation gate for agent-authored SQL.

First layer of a defense in depth: a single read-only SELECT over explicitly
whitelisted relations, no comments, no extra statements. The statement is
parsed to a real AST (sqlglot, Postgres dialect), so the statement-type and
relation-whitelist checks reason over structure instead of tokens — a quoted
relation, a table-valued function, or a derived-table alias is judged by what
it *is*, not by how it lexes. Lexical pre-checks still reject what a parser
would silently absorb (comments) or mangle (dollar-quoting, an unterminated
string). Execution adds the database-level layers (the `sql_tool_ro` role,
granted only on the `registers.v_*` views, inside a read-only transaction in
Postgres; external access disabled in DuckDB). The guard prefers false
rejections over false accepts — anything it cannot positively account for is
refused with a reason the agent can act on.
"""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

# Statement roots the guard accepts: a plain SELECT or a set operation over
# SELECTs. Anything else (INSERT, EXPLAIN, DDL, ...) is not a SELECT.
_SELECT_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)


class SqlGuardError(ValueError):
    """Agent-authored SQL failed validation; the message says why."""


_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")
_QUOTED_IDENTIFIER_RE = re.compile(r'"[^"]*"')
_FROM_RE = re.compile(r"\bfrom\b", re.IGNORECASE)
_CLAUSE_END_RE = re.compile(
    r"\b(where|group|order|having|limit|offset|window|union|intersect|except)\b", re.IGNORECASE
)

# Statement types and side-effect keywords that have no place in a read-only
# SELECT. Includes DuckDB-specific escape hatches (pragma/install/load/attach).
_FORBIDDEN_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "grant",
    "revoke",
    "truncate",
    "copy",
    "call",
    "do",
    "execute",
    "prepare",
    "deallocate",
    "declare",
    "fetch",
    "lock",
    "comment",
    "merge",
    "vacuum",
    "analyze",
    "listen",
    "notify",
    "set",
    "reset",
    "begin",
    "commit",
    "rollback",
    "savepoint",
    "attach",
    "detach",
    "pragma",
    "install",
    "load",
    "import",
    "export",
    "refresh",
)
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(_FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE)

# Server-side functions callable from a SELECT list that sleep, touch the
# filesystem, or change session state — the relation whitelist never sees them.
_DANGEROUS_FUNCTION_RE = re.compile(
    r"\b(pg_[a-z0-9_]*|set_config|dblink[a-z0-9_]*|lo_[a-z0-9_]*|xpath|query_to_xml[a-z_]*)\s*\(",
    re.IGNORECASE,
)


# Structural allowlist of function nodes, by sqlglot expression class. The
# regex above only sees unquoted names; a quoted or schema-qualified call such
# as "pg_sleep"(1) or pg_catalog."set_config"(...) reaches the AST as an
# Anonymous node, which is refused unless its name is listed below. Boolean
# connectives and CASE are Func subclasses in sqlglot, hence their presence.
_ALLOWED_FUNCTION_CLASSES = frozenset(
    {
        "And",
        "Or",
        "Xor",
        "Case",
        "If",
        "Coalesce",
        "Nullif",
        "Greatest",
        "Least",
        "Count",
        "Sum",
        "Avg",
        "Min",
        "Max",
        "ArrayAgg",
        "GroupConcat",
        "Stddev",
        "StddevPop",
        "StddevSamp",
        "Variance",
        "VariancePop",
        "Lower",
        "Upper",
        "Length",
        "Trim",
        "Concat",
        "ConcatWs",
        "Substring",
        "Round",
        "Abs",
        "Floor",
        "Ceil",
        "Extract",
        "DateTrunc",
        "TimestampTrunc",
        "CurrentDate",
        "CurrentTimestamp",
        "TimeToStr",
        "Cast",
        "TryCast",
        "RowNumber",
        "Rank",
        "DenseRank",
    }
)
# Postgres functions sqlglot does not model, matched case-insensitively.
_ALLOWED_ANONYMOUS_FUNCTIONS = frozenset({"age", "date_part"})


def validate_select(sql: str, *, allowed_relations: frozenset[str]) -> str:
    """Return the validated statement (trailing semicolon stripped) or raise."""
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise SqlGuardError("empty SQL statement")

    # Lexical pre-checks: reject what the parser would silently swallow
    # (comments) or must be caught before parsing can mangle it (dollar-quoting,
    # an unterminated string literal). The forbidden-keyword and comma-join
    # scans below run on this neutralized text so quoted identifiers and string
    # literals cannot hide or fake a keyword.
    scan = _STRING_LITERAL_RE.sub("''", statement)
    if "'" in scan.replace("''", ""):
        raise SqlGuardError("unbalanced or escaped string literal")
    if scan.count('"') % 2 != 0:
        raise SqlGuardError("unbalanced double-quoted identifier")
    scan = _QUOTED_IDENTIFIER_RE.sub("qid", scan)
    if "$" in scan:
        raise SqlGuardError("dollar-quoting and positional parameters are not allowed")
    if "--" in scan or "/*" in scan or "*/" in scan:
        raise SqlGuardError("SQL comments are not allowed")

    # Structural checks over the parsed AST: exactly one statement, and it is a
    # SELECT / set operation (this refuses INSERT, EXPLAIN, DDL with "only
    # SELECT" before the keyword scan can report a narrower reason).
    tree = _parse_single_select(statement)

    # Side-effect keywords (FOR UPDATE, DO, ...) that parse as innocuous nodes
    # yet must not run in a read-only SELECT.
    forbidden = _FORBIDDEN_RE.search(scan)
    if forbidden:
        raise SqlGuardError(f"forbidden keyword: {forbidden.group(1).upper()}")

    dangerous = _DANGEROUS_FUNCTION_RE.search(scan)
    if dangerous:
        raise SqlGuardError(f"function not allowed: {dangerous.group(1)}")

    _reject_comma_joins(scan)
    _reject_disallowed_relations(tree, allowed_relations)
    _reject_disallowed_functions(tree)

    return statement


def _parse_single_select(statement: str) -> exp.Expression:
    """Parse to one SELECT-rooted AST or raise with the governing reason."""
    try:
        statements = [s for s in sqlglot.parse(statement, read="postgres") if s is not None]
    except ParseError as exc:
        raise SqlGuardError(f"unparseable SQL statement: {exc}") from exc
    if len(statements) != 1:
        raise SqlGuardError("multiple SQL statements are not allowed")
    tree = statements[0]
    if not isinstance(tree, _SELECT_ROOTS):
        raise SqlGuardError("only SELECT statements are allowed")
    return tree


def _reject_disallowed_functions(tree: exp.Expression) -> None:
    """Every function call must be on the allowlist, however it is quoted or
    qualified. Judged on the AST so identifier quoting cannot hide a call."""
    for node in tree.find_all(exp.Func):
        if isinstance(node, exp.Anonymous):
            name = node.name
            if name.lower() in _ALLOWED_ANONYMOUS_FUNCTIONS:
                continue
            raise SqlGuardError(f"function not allowed: {name}")
        if type(node).__name__ not in _ALLOWED_FUNCTION_CLASSES:
            raise SqlGuardError(f"function not allowed: {node.sql_name().lower()}")


def _reject_disallowed_relations(tree: exp.Expression, allowed_relations: frozenset[str]) -> None:
    """Every base relation must be whitelisted. CTE names and derived-table
    aliases are internal scopes, not base relations; a table-valued function in
    FROM (unnest, read_csv_auto, ...) is never a curated view.
    """
    if next(tree.find_all(exp.Unnest), None) is not None:
        raise SqlGuardError("relation not allowed: table-valued function in FROM")
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    allowed_lower = {name.lower() for name in allowed_relations}
    for table in tree.find_all(exp.Table):
        name = ".".join(part for part in (table.catalog, table.db, table.name) if part)
        if name.lower() in cte_names:
            continue
        if name and name.lower() in allowed_lower:
            continue
        allowed = ", ".join(sorted(allowed_relations))
        raise SqlGuardError(f"relation not allowed: {name!r} (allowed: {allowed})")


def _reject_comma_joins(scan: str) -> None:
    """Comma-separated FROM lists are refused in favor of explicit JOIN syntax:
    the parsed whitelist would still catch an unlisted relation, but requiring
    JOINs keeps the authored surface unambiguous and easy to review.
    """
    for match in _FROM_RE.finditer(scan):
        depth = 0
        i = match.end()
        while i < len(scan):
            char = scan[i]
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0:
                if char == ",":
                    raise SqlGuardError("comma-separated FROM lists are not allowed; use JOIN")
                if char.isalpha() and _CLAUSE_END_RE.match(scan, i):
                    break
            i += 1
