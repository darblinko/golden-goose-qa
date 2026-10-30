"""replace_graph wipes and reloads the derived graph inside one write
transaction, so a failure part-way leaves the previous graph committed."""

import pytest
from gg_ingestion.extract.graph_load import WIPE_DERIVED_QUERY, replace_graph
from gg_ingestion.extract.model import Edge, Node, Provenance


class _Result:
    async def consume(self):
        return None


class _Tx:
    def __init__(self, store, fail_on: str | None):
        self._store = store
        self._fail_on = fail_on
        self.pending: list[str] = []

    async def run(self, query, parameters):
        if self._fail_on and self._fail_on in query:
            raise RuntimeError("neo4j unavailable")
        self.pending.append(query)
        return _Result()


class _Session:
    def __init__(self, store, fail_on):
        self._store = store
        self._fail_on = fail_on

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute_write(self, work):
        tx = _Tx(self._store, self._fail_on)
        await work(tx)  # an exception here rolls the transaction back
        self._store["transactions"] += 1
        self._store["committed"] = tx.pending

    async def run(self, *args, **kwargs):
        raise AssertionError("graph writes must go through one managed transaction")


class _Driver:
    def __init__(self, fail_on: str | None = None):
        self.store = {"transactions": 0, "committed": ["previous graph"]}
        self._fail_on = fail_on

    def session(self):
        return _Session(self.store, self._fail_on)


_NODES = [Node(label="Document", key="SOP-004", properties={"title": "t"})]
_EDGES = [
    Edge(
        rel_type="VERIFIES",
        start_label="Document",
        start_key="VTR-001",
        end_label="Requirement",
        end_key="REQ-001",
        provenance=Provenance(doc_key="VTR-001", method="form_field", locator="row 4"),
        properties={},
    )
]


async def test_wipe_and_load_commit_in_one_transaction():
    driver = _Driver()
    await replace_graph(driver, _NODES, _EDGES)
    committed = driver.store["committed"]
    assert driver.store["transactions"] == 1
    assert committed[0] == WIPE_DERIVED_QUERY
    assert any("MERGE (n:Document" in q for q in committed)
    assert any("VERIFIES" in q for q in committed)


async def test_failed_edge_load_leaves_previous_graph():
    driver = _Driver(fail_on="VERIFIES")
    with pytest.raises(RuntimeError):
        await replace_graph(driver, _NODES, _EDGES)
    assert driver.store == {"transactions": 0, "committed": ["previous graph"]}
