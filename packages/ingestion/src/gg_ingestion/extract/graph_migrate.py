"""Cypher schema migrations, tracked in-graph.

Files in infra/migrations/cypher/ apply in name order; each applied file is
recorded as a :SchemaMigration node so reruns are no-ops. Statements use
IF NOT EXISTS so a half-applied file is safe to re-run.
"""

from pathlib import Path

from gg_common.graphstore import run_read, run_write
from neo4j import AsyncDriver

_TRACKING_QUERY = "MERGE (m:SchemaMigration {name: $name}) SET m.applied_at = datetime()"


def statements(cypher_text: str) -> list[str]:
    lines = [line for line in cypher_text.splitlines() if not line.strip().startswith("//")]
    return [part.strip() for part in "\n".join(lines).split(";") if part.strip()]


async def applied_migrations(driver: AsyncDriver) -> set[str]:
    rows = await run_read(driver, "MATCH (m:SchemaMigration) RETURN m.name AS name")
    return {row["name"] for row in rows}


async def apply_migrations(driver: AsyncDriver, migrations_dir: Path) -> list[str]:
    if not migrations_dir.is_dir():
        raise FileNotFoundError(f"cypher migrations directory not found: {migrations_dir}")
    done = await applied_migrations(driver)
    applied: list[str] = []
    for path in sorted(migrations_dir.glob("*.cypher")):
        if path.stem in done:
            continue
        for statement in statements(path.read_text()):
            await run_write(driver, statement)
        await run_write(driver, _TRACKING_QUERY, {"name": path.stem})
        applied.append(path.stem)
    return applied
