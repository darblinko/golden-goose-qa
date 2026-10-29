"""Per-node routing eval: does each golden question reach a node that can
answer it?

Scores the deterministic routing layer (regex overrides + the default), which
is exactly what runs in keyless deployments and is the audit-critical
component per ADR 0016. The LLM router refines within the acceptable set;
this eval guards the floor it falls back to.
"""

from dataclasses import dataclass

from gg_agents.state import DEFAULT_PATTERN
from gg_agents.toolselect import route_override

from gg_evals.retrieval_eval import EvalItem

# Fallback QA pattern -> acceptable routes, used only for ad-hoc items (unit
# tests, older QA files) that carry no generator-emitted expected_routes. The
# generator is the source of truth (gg_synthdata.qa._PATTERN_ROUTES); this table
# mirrors it so the fallback and the emitted values agree. A question routed
# outside its set lands on a node that cannot produce the golden answer, which
# is a routing defect regardless of downstream behavior.
EXPECTED_ROUTES: dict[str, frozenset[str]] = {
    "procedure_content": frozenset({"procedure", "record"}),
    "defect_discovery": frozenset({"record", "procedure", "trace", "aggregate"}),
    "revision_approval": frozenset({"revision", "record", "trace"}),
    "trace_walk": frozenset({"trace"}),
    "training": frozenset({"trace"}),
    "fmea_risk": frozenset({"fmea", "record"}),
    "capa_thread": frozenset({"record", "aggregate"}),
    "complaint_mdr": frozenset({"record", "aggregate", "external"}),
    "counts_aggregates": frozenset({"aggregate"}),
    "supplier": frozenset({"record", "aggregate", "trace"}),
    # Crosswalk questions are procedure content asked in ISO/CFR dialect; a
    # cited CFR clause legitimately triggers the external route, which still
    # retrieves internally alongside the regulation text.
    "regulatory_crosswalk": frozenset({"procedure", "record", "external"}),
    # Audit/management-review/clinical record lookups only. `aggregate` is
    # deliberately excluded: the management-review "how many CAPAs were opened"
    # questions route to aggregate on count phrasing but must be answered from
    # the review record, so they misroute and show red until the composite
    # record+count path lands. The gate is not relaxed to hide a genuine
    # misroute.
    "governance_clinical": frozenset({"record"}),
}


def deterministic_route(question: str) -> str:
    return route_override(question) or DEFAULT_PATTERN


@dataclass(frozen=True)
class RoutingResult:
    item_id: str
    pattern: str
    route: str
    acceptable: bool


@dataclass(frozen=True)
class RoutingReport:
    results: tuple[RoutingResult, ...]

    @property
    def accuracy(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.acceptable) / len(self.results)

    def misroutes(self) -> tuple[RoutingResult, ...]:
        return tuple(r for r in self.results if not r.acceptable)

    def as_dict(self) -> dict[str, object]:
        return {
            "n_items": len(self.results),
            "accuracy": round(self.accuracy, 4),
            "misroutes": [
                {"item_id": r.item_id, "pattern": r.pattern, "route": r.route}
                for r in self.misroutes()
            ],
        }


def acceptable_routes(item: EvalItem) -> frozenset[str]:
    """Prefer the routes the generator emitted for this item; fall back to the
    per-pattern table for ad-hoc items that carry none. An unknown pattern with
    no per-item routes is an error, not a silent skip."""
    if item.expected_routes:
        return frozenset(item.expected_routes)
    acceptable = EXPECTED_ROUTES.get(item.pattern)
    if acceptable is None:
        raise ValueError(f"no expected routes for QA pattern {item.pattern!r}")
    return acceptable


def evaluate_routing(items: list[EvalItem]) -> RoutingReport:
    """Route every item (no retrievability filter — routing is upstream of
    retrieval, and aggregate questions matter most here)."""
    results = []
    for item in items:
        route = deterministic_route(item.question)
        results.append(
            RoutingResult(
                item_id=item.id,
                pattern=item.pattern,
                route=route,
                acceptable=route in acceptable_routes(item),
            )
        )
    return RoutingReport(results=tuple(results))
