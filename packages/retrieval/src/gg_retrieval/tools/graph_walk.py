"""Whitelisted multi-hop traversals over the derived knowledge graph.

The agent never writes Cypher: each traversal is a fixed, parameterized
query set matching the schema loaded by `gg-ingest derive`. Edge rows carry
the source_doc_key provenance stamped at extraction time, so every hop in an
answer can cite the document it was read from.
"""

from typing import Any

from gg_common.graphstore import run_read
from gg_common.settings import AppSettings
from neo4j import AsyncDriver

from gg_retrieval.tools.models import ToolResult, plain_row

# Uniform shape for traversal output: one row per edge, plus a leading
# row describing the anchor entity itself.
EDGE_COLUMNS = ("relation", "from_key", "to_key", "detail", "source_doc")

_THREAD_RELS = "SOURCED_FROM|ESCALATED_TO|FILED_AS|FROM_COMPLAINT|FROM_SUPPLIER|EVALUATED_AGAINST"

_REQUIREMENT_QUERY = """
MATCH (r:Requirement {req_id: $req_id})
RETURN r.req_id AS req_id, r.category AS category, r.text AS text,
       r.source_doc_key AS source_doc, r.locator AS locator
"""

_SATISFIES_QUERY = """
MATCH (o:DesignOutput)-[e:SATISFIES]->(r:Requirement {req_id: $req_id})
RETURN o.do_id AS from_key, e.source_doc_key AS source_doc
ORDER BY from_key
"""

_VERIFIES_QUERY = """
MATCH (d:Document)-[e:VERIFIES]->(r:Requirement {req_id: $req_id})
RETURN d.doc_key AS from_key, e.protocol_id AS protocol_id, e.result AS result,
       e.source_doc_key AS source_doc
ORDER BY from_key
"""

_UNVERIFIED_QUERY = """
MATCH (r:Requirement)
WHERE NOT ()-[:VERIFIES]->(r)
RETURN r.req_id AS req_id, r.category AS category, r.text AS requirement_text,
       r.source_doc_key AS source_doc, r.locator AS locator
ORDER BY r.req_id
"""

_DOCUMENT_QUERY = """
MATCH (d:Document {doc_key: $doc_key})
RETURN d.doc_type AS doc_type, d.title AS title, d.revision AS revision,
       d.effective_from AS effective_from
"""

_REVISIONS_QUERY = """
MATCH (d:Document {doc_key: $doc_key})-[:HAS_REVISION]->(rev:DocumentRevision)
RETURN rev.revision AS revision, rev.effective_date AS effective_date,
       rev.description AS description, rev.author AS author, rev.approved_by AS approved_by
ORDER BY revision
"""

_REFERENCES_OUT_QUERY = """
MATCH (d:Document {doc_key: $doc_key})-[e:REFERENCES]->(t:Document)
RETURN t.doc_key AS doc_key, e.locator AS locator, e.source_doc_key AS source_doc
ORDER BY doc_key
"""

_REFERENCES_IN_QUERY = """
MATCH (s:Document)-[e:REFERENCES]->(d:Document {doc_key: $doc_key})
RETURN s.doc_key AS doc_key, e.locator AS locator, e.source_doc_key AS source_doc
ORDER BY doc_key
"""

_FMEA_MISMATCH_QUERY = """
MATCH (f:FmeaRow)
WHERE f.ap_mismatch
RETURN f.doc_key AS doc_key, f.row_id AS row_id, f.item AS item,
       f.failure_mode AS failure_mode, f.severity AS severity, f.occurrence AS occurrence,
       f.detection AS detection, f.ap_recorded AS ap_recorded, f.ap_computed AS ap_computed
ORDER BY doc_key, row_id
"""

_STALE_REFERENCES_QUERY = """
MATCH (s:Document)-[e:REFERENCES]->(t:Document)
WHERE e.cited_revision IS NOT NULL AND t.revision IS NOT NULL
  AND e.cited_revision <> t.revision
RETURN s.doc_key AS doc_key, t.doc_key AS referenced_doc,
       e.cited_revision AS cited_revision, t.revision AS current_revision,
       e.locator AS locator, e.source_doc_key AS source_doc
ORDER BY doc_key, referenced_doc
"""

_STALE_TRAINING_QUERY = """
MATCH (p:Person)-[t:TRAINED_ON]->(d:Document)
WHERE t.revision IS NOT NULL AND d.revision IS NOT NULL
  AND t.revision <> d.revision
RETURN p.name AS person, p.role AS role, d.doc_key AS doc_key,
       t.revision AS trained_revision, d.revision AS current_revision,
       t.source_doc_key AS source_doc
ORDER BY person, doc_key
"""

_TRAINING_QUERY = """
MATCH (p:Person)-[t:TRAINED_ON]->(d:Document {doc_key: $doc_key})
RETURN p.name AS person, p.role AS role, t.revision AS trained_revision,
       t.trained_on AS trained_on, d.revision AS current_revision,
       t.source_doc_key AS source_doc
ORDER BY person
"""

_SUPPLIER_QUERY = """
MATCH (s:Supplier {supplier_id: $supplier_id})
RETURN s.name AS name, s.commodity AS commodity, s.approval_status AS approval_status,
       s.last_audit AS last_audit
"""

_SUPPLIER_AUDITS_QUERY = """
MATCH (d:Document)-[e:AUDITS]->(s:Supplier {supplier_id: $supplier_id})
RETURN d.doc_key AS doc_key, e.source_doc_key AS source_doc
ORDER BY doc_key
"""

_SUPPLIER_NCRS_QUERY = """
MATCH (n:Document)-[e:FROM_SUPPLIER]->(s:Supplier {supplier_id: $supplier_id})
RETURN n.doc_key AS doc_key, e.source_doc_key AS source_doc
ORDER BY doc_key
"""


def _thread_query(hops: int) -> str:
    # Variable-length bounds cannot be Cypher parameters; the value is an int
    # from validated settings, never model-authored input.
    return f"""
MATCH (d:Document {{doc_key: $doc_key}})
MATCH p = (d)-[:{_THREAD_RELS}*1..{int(hops)}]-(x)
UNWIND relationships(p) AS rel
WITH DISTINCT rel
RETURN type(rel) AS relation,
       coalesce(startNode(rel).doc_key, startNode(rel).supplier_id) AS from_key,
       coalesce(endNode(rel).doc_key, endNode(rel).supplier_id) AS to_key,
       rel.source_doc_key AS source_doc
ORDER BY relation, from_key, to_key
"""


class GraphWalker:
    def __init__(self, *, driver: AsyncDriver, settings: AppSettings) -> None:
        self.driver = driver
        self.settings = settings

    async def requirement_trace(self, req_id: str) -> ToolResult:
        params = {"req_id": req_id}
        requirement = await run_read(self.driver, _REQUIREMENT_QUERY, params)
        if not requirement:
            return self._result(
                title=f"Requirement trace: {req_id} (not in graph)",
                query=f"requirement_trace({req_id})",
                columns=EDGE_COLUMNS,
                rows=[],
                anchor_missing=True,
            )
        found = requirement[0]
        detail = f"[{found['category']}] {found['text']}"
        if found.get("locator"):
            detail = f"{detail} (defined at {found['locator']})"
        rows: list[dict[str, Any]] = [
            {
                "relation": "REQUIREMENT",
                "from_key": req_id,
                "to_key": "",
                "detail": detail,
                "source_doc": found.get("source_doc"),
            }
        ]
        for record in await run_read(self.driver, _SATISFIES_QUERY, params):
            rows.append(_edge_row("SATISFIES", record["from_key"], req_id, "", record))
        for record in await run_read(self.driver, _VERIFIES_QUERY, params):
            detail = _join_details(
                ("protocol", record.get("protocol_id")), ("result", record.get("result"))
            )
            rows.append(_edge_row("VERIFIES", record["from_key"], req_id, detail, record))
        return self._result(
            title=f"Requirement trace: {req_id}",
            query=f"requirement_trace({req_id})",
            columns=EDGE_COLUMNS,
            rows=rows,
        )

    async def unverified_requirements(self) -> ToolResult:
        rows = await run_read(self.driver, _UNVERIFIED_QUERY)
        return self._result(
            title="Requirements with no verification report",
            query="unverified_requirements()",
            columns=("req_id", "category", "requirement_text", "source_doc", "locator"),
            rows=rows,
        )

    async def document_profile(self, doc_key: str) -> ToolResult:
        params = {"doc_key": doc_key}
        document = await run_read(self.driver, _DOCUMENT_QUERY, params)
        if not document:
            return self._result(
                title=f"Document profile: {doc_key} (not in graph)",
                query=f"document_profile({doc_key})",
                columns=EDGE_COLUMNS,
                rows=[],
                anchor_missing=True,
            )
        found = document[0]
        detail = _join_details(
            ("type", found.get("doc_type")),
            ("title", found.get("title")),
            ("revision", found.get("revision")),
            ("effective", found.get("effective_from")),
        )
        rows: list[dict[str, Any]] = [
            {
                "relation": "DOCUMENT",
                "from_key": doc_key,
                "to_key": "",
                "detail": detail,
                "source_doc": doc_key,
            }
        ]
        for record in await run_read(self.driver, _REVISIONS_QUERY, params):
            revision_detail = _join_details(
                ("effective", record.get("effective_date")),
                ("description", record.get("description")),
                ("author", record.get("author")),
                ("approved by", record.get("approved_by")),
            )
            rows.append(
                _edge_row(
                    "HAS_REVISION",
                    doc_key,
                    f"Rev {record['revision']}",
                    revision_detail,
                    {"source_doc": doc_key},
                )
            )
        for record in await run_read(self.driver, _REFERENCES_OUT_QUERY, params):
            detail = _join_details(("at", record.get("locator")))
            rows.append(_edge_row("REFERENCES", doc_key, record["doc_key"], detail, record))
        for record in await run_read(self.driver, _REFERENCES_IN_QUERY, params):
            detail = _join_details(("at", record.get("locator")))
            rows.append(_edge_row("REFERENCED_BY", record["doc_key"], doc_key, detail, record))
        return self._result(
            title=f"Document profile: {doc_key}",
            query=f"document_profile({doc_key})",
            columns=EDGE_COLUMNS,
            rows=rows,
        )

    async def record_thread(self, doc_key: str) -> ToolResult:
        hops = self.settings.tools.graph_record_hops
        document = await run_read(self.driver, _DOCUMENT_QUERY, {"doc_key": doc_key})
        if not document:
            # The record itself is absent from the graph. An empty thread here is
            # "not in corpus," not "a record with no links" — flag it so a walk
            # for a nonexistent CAPA is never cited as a grounded empty result.
            return self._result(
                title=f"Record thread around {doc_key} (not in graph)",
                query=f"record_thread({doc_key})",
                columns=EDGE_COLUMNS,
                rows=[],
                anchor_missing=True,
            )
        rows = [
            _edge_row(r["relation"], r["from_key"], r["to_key"], "", r)
            for r in await run_read(self.driver, _thread_query(hops), {"doc_key": doc_key})
        ]
        return self._result(
            title=f"Record thread around {doc_key} (up to {hops} hops)",
            query=f"record_thread({doc_key})",
            columns=EDGE_COLUMNS,
            rows=rows,
        )

    async def fmea_ap_mismatches(self) -> ToolResult:
        rows = await run_read(self.driver, _FMEA_MISMATCH_QUERY)
        return self._result(
            title="FMEA rows where recorded AP disagrees with computed AP",
            query="fmea_ap_mismatches()",
            columns=(
                "doc_key",
                "row_id",
                "item",
                "failure_mode",
                "severity",
                "occurrence",
                "detection",
                "ap_recorded",
                "ap_computed",
            ),
            rows=rows,
            doc_keys=[str(r["doc_key"]) for r in rows],
        )

    async def stale_references(self) -> ToolResult:
        rows = await run_read(self.driver, _STALE_REFERENCES_QUERY)
        return self._result(
            title="Documents citing a superseded revision of another document",
            query="stale_references()",
            columns=(
                "doc_key",
                "referenced_doc",
                "cited_revision",
                "current_revision",
                "locator",
            ),
            rows=rows,
        )

    async def stale_training(self) -> ToolResult:
        rows = await run_read(self.driver, _STALE_TRAINING_QUERY)
        return self._result(
            title="Training records against a superseded document revision",
            query="stale_training()",
            columns=("person", "role", "doc_key", "trained_revision", "current_revision"),
            rows=rows,
        )

    async def training_status(self, doc_key: str) -> ToolResult:
        columns = ("person", "role", "trained_revision", "trained_on", "current_revision")
        document = await run_read(self.driver, _DOCUMENT_QUERY, {"doc_key": doc_key})
        if not document:
            # The document itself is absent — an empty training lookup here is
            # "not in corpus," not "nobody is trained." Flag it so the agent
            # answers honestly rather than citing an empty table as grounded.
            return self._result(
                title=f"Training status for {doc_key} (not in graph)",
                query=f"training_status({doc_key})",
                columns=columns,
                rows=[],
                anchor_missing=True,
            )
        rows = await run_read(self.driver, _TRAINING_QUERY, {"doc_key": doc_key})
        return self._result(
            title=f"Training status for {doc_key}",
            query=f"training_status({doc_key})",
            columns=columns,
            rows=rows,
        )

    async def supplier_profile(self, supplier_id: str) -> ToolResult:
        params = {"supplier_id": supplier_id}
        supplier = await run_read(self.driver, _SUPPLIER_QUERY, params)
        if not supplier:
            return self._result(
                title=f"Supplier profile: {supplier_id} (not in graph)",
                query=f"supplier_profile({supplier_id})",
                columns=EDGE_COLUMNS,
                rows=[],
                anchor_missing=True,
            )
        found = supplier[0]
        detail = _join_details(
            ("name", found.get("name")),
            ("commodity", found.get("commodity")),
            ("status", found.get("approval_status")),
            ("last audit", found.get("last_audit")),
        )
        rows: list[dict[str, Any]] = [
            {
                "relation": "SUPPLIER",
                "from_key": supplier_id,
                "to_key": "",
                "detail": detail,
                "source_doc": None,
            }
        ]
        for record in await run_read(self.driver, _SUPPLIER_AUDITS_QUERY, params):
            rows.append(_edge_row("AUDITS", record["doc_key"], supplier_id, "", record))
        for record in await run_read(self.driver, _SUPPLIER_NCRS_QUERY, params):
            rows.append(_edge_row("FROM_SUPPLIER", record["doc_key"], supplier_id, "", record))
        return self._result(
            title=f"Supplier profile: {supplier_id}",
            query=f"supplier_profile({supplier_id})",
            columns=EDGE_COLUMNS,
            rows=rows,
        )

    def _result(
        self,
        *,
        title: str,
        query: str,
        columns: tuple[str, ...],
        rows: list[dict[str, Any]],
        doc_keys: list[str] | None = None,
        anchor_missing: bool = False,
    ) -> ToolResult:
        limit = self.settings.tools.graph_row_limit
        truncated = len(rows) > limit
        kept = [plain_row(row) for row in rows[:limit]]
        if doc_keys is None:
            doc_keys = [str(row["source_doc"]) for row in kept if row.get("source_doc")]
        return ToolResult(
            tool="graph_walk",
            title=title,
            source="knowledge graph (derived from corpus extraction)",
            query=query,
            columns=columns,
            rows=tuple(kept),
            truncated=truncated,
            source_doc_keys=tuple(dict.fromkeys(doc_keys)),
            anchor_missing=anchor_missing,
        )


def _edge_row(
    relation: str, from_key: Any, to_key: Any, detail: str, record: dict[str, Any]
) -> dict[str, Any]:
    return {
        "relation": relation,
        "from_key": from_key,
        "to_key": to_key,
        "detail": detail,
        "source_doc": record.get("source_doc"),
    }


def _join_details(*pairs: tuple[str, Any]) -> str:
    parts = [f"{label} {value}" for label, value in pairs if value not in (None, "")]
    return ", ".join(parts)
