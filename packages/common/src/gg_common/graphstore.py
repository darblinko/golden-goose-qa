"""Neo4j driver seam.

The graph store sits behind this thin module so callers never import the
neo4j driver directly — swapping to FalkorDB (documented fallback) or a
cloud-hosted Neo4j means changing only this seam and the settings.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from gg_common.settings import Neo4jSettings


def create_graph_driver(settings: Neo4jSettings) -> AsyncDriver:
    return AsyncGraphDatabase.driver(
        settings.uri,
        auth=(settings.user, settings.password.get_secret_value()),
    )


@asynccontextmanager
async def graph_driver(settings: Neo4jSettings) -> AsyncIterator[AsyncDriver]:
    driver = create_graph_driver(settings)
    try:
        yield driver
    finally:
        await driver.close()


async def run_write(
    driver: AsyncDriver, query: str, parameters: dict[str, Any] | None = None
) -> None:
    async with driver.session() as session:
        await session.run(query, parameters or {})


async def run_read(
    driver: AsyncDriver, query: str, parameters: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    async with driver.session() as session:
        result = await session.run(query, parameters or {})
        return [dict(record) async for record in result]
