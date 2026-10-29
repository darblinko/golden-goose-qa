"""Runs the audit-readiness gates and shapes the report.

Each check runs independently: a failing datastore turns that one check
into an "error" result instead of sinking the report, because a partially
answered readiness question is still worth showing during audit prep.
"""

from dataclasses import dataclass
from typing import Any, Literal

from gg_retrieval.audit.checks import (
    AUDIT_CHECKS,
    COLLECTIONS_BY_ID,
    AuditCheck,
)
from gg_retrieval.tools.graph_walk import GraphWalker
from gg_retrieval.tools.models import ToolResult
from gg_retrieval.tools.warehouse import WarehouseTool

CheckStatus = Literal["pass", "finding", "error"]


@dataclass(frozen=True)
class CheckResult:
    check: AuditCheck
    status: CheckStatus
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    truncated: bool
    source: str
    detail: str  # why the check errored; empty otherwise


@dataclass(frozen=True)
class AuditReport:
    collection_id: str | None
    results: tuple[CheckResult, ...]

    @property
    def findings(self) -> tuple[CheckResult, ...]:
        return tuple(r for r in self.results if r.status == "finding")

    @property
    def errors(self) -> tuple[CheckResult, ...]:
        return tuple(r for r in self.results if r.status == "error")

    @property
    def summary(self) -> str:
        finding_rows = sum(len(r.rows) for r in self.findings)
        parts = [
            f"{len(self.results)} checks run",
            f"{len(self.findings)} with findings ({finding_rows} rows)",
        ]
        if self.errors:
            parts.append(f"{len(self.errors)} could not run")
        return "; ".join(parts) + "."


class AuditReportRunner:
    def __init__(self, *, warehouse: WarehouseTool, graph: GraphWalker) -> None:
        self.warehouse = warehouse
        self.graph = graph

    async def run(self, collection_id: str | None = None) -> AuditReport:
        checks = _resolve_checks(collection_id)
        results = [await self._run_check(check) for check in checks]
        return AuditReport(collection_id=collection_id, results=tuple(results))

    async def _run_check(self, check: AuditCheck) -> CheckResult:
        try:
            if check.source == "warehouse":
                result = await self.warehouse.run_saved(check.ref)
            else:
                result = await self._run_graph(check.ref)
        except Exception as exc:
            return CheckResult(
                check=check,
                status="error",
                columns=(),
                rows=(),
                truncated=False,
                source="",
                detail=f"{type(exc).__name__}: {exc}",
            )
        return CheckResult(
            check=check,
            status="finding" if result.rows else "pass",
            columns=result.columns,
            rows=result.rows,
            truncated=result.truncated,
            source=result.source,
            detail="",
        )

    async def _run_graph(self, ref: str) -> ToolResult:
        method = getattr(self.graph, ref)
        result = await method()
        if not isinstance(result, ToolResult):
            raise TypeError(f"graph check '{ref}' returned {type(result).__name__}")
        return result


def _resolve_checks(collection_id: str | None) -> tuple[AuditCheck, ...]:
    if collection_id is None:
        return AUDIT_CHECKS
    collection = COLLECTIONS_BY_ID.get(collection_id)
    if collection is None:
        available = ", ".join(sorted(COLLECTIONS_BY_ID))
        raise LookupError(f"unknown audit collection: {collection_id} (available: {available})")
    return tuple(
        check for check in AUDIT_CHECKS if check.check_id in frozenset(collection.check_ids)
    )
