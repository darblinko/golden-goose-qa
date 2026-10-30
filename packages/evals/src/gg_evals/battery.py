"""The full eval battery: retrieval, end-to-end answers, routing, and noise
sensitivity in one run, with gates that fail loudly.

Assembles the same dependency stack the API lifespan builds, with two
deliberate differences: no checkpointer (eval turns are independent) and
external tools forced offline (openFDA and eCFR need no API key, so a nightly
run would otherwise silently depend on live third-party endpoints and network
weather — determinism wins).
"""

from dataclasses import dataclass

from gg_agents.graph import build_agent_graph
from gg_agents.nodes import AgentDeps
from gg_common.db import create_engine, create_session_factory
from gg_common.graphstore import create_graph_driver
from gg_common.providers.factory import build_providers
from gg_common.settings import AppSettings
from gg_retrieval.retriever import HybridRetriever
from gg_retrieval.tools.external.toolkit import build_external_toolkit
from gg_retrieval.tools.graph_walk import GraphWalker
from gg_retrieval.tools.warehouse import WarehouseTool
from qdrant_client import AsyncQdrantClient

from gg_evals.answer_eval import AnswerReport, evaluate_answers
from gg_evals.invariants import (
    FULL_INVARIANTS,
    SMOKE_INVARIANTS,
    CoverageInvariants,
    coverage_failures,
)
from gg_evals.noise import NoiseReport, evaluate_noise
from gg_evals.retrieval_eval import EvalItem, EvalReport, evaluate
from gg_evals.routing_eval import RoutingReport, evaluate_routing


@dataclass(frozen=True)
class BatteryThresholds:
    recall: float = 0.8
    grounded_rate: float = 0.8
    support: float = 0.5
    # Citation floors are provisional — set below expected performance so an
    # ordinary run passes, and tightened once the nightly establishes a
    # baseline. Both average over grounded answers only (answer_eval), so an
    # insufficient_evidence verdict is penalized through grounded_rate, not here.
    citation_precision: float = 0.5
    citation_recall: float = 0.5
    # Task checks have one right answer each (a register count), so any wrong
    # checked answer fails the run.
    answer_correctness: float = 1.0
    routing_accuracy: float = 0.9
    max_noise_degradation: float = 0.15


DEFAULT_THRESHOLDS = BatteryThresholds()


@dataclass(frozen=True)
class BatteryReport:
    retrieval: EvalReport
    answers: AnswerReport
    routing: RoutingReport
    noise: NoiseReport
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, object]:
        return {
            "retrieval": self.retrieval.as_dict(),
            "answers": self.answers.as_dict(),
            "routing": self.routing.as_dict(),
            "noise": self.noise.as_dict(),
            "failures": list(self.failures),
        }


def gate_failures(
    retrieval: EvalReport,
    answers: AnswerReport,
    routing: RoutingReport,
    noise: NoiseReport,
    thresholds: BatteryThresholds,
) -> tuple[str, ...]:
    checks = [
        ("retrieval recall", retrieval.recall, thresholds.recall, True),
        ("grounded rate", answers.grounded_rate, thresholds.grounded_rate, True),
        ("answer support", answers.support, thresholds.support, True),
        ("citation precision", answers.citation_precision, thresholds.citation_precision, True),
        ("citation recall", answers.citation_recall, thresholds.citation_recall, True),
        ("routing accuracy", routing.accuracy, thresholds.routing_accuracy, True),
        ("noise degradation", noise.degradation, thresholds.max_noise_degradation, False),
    ]
    if answers.checked():
        checks.append(
            ("answer correctness", answers.correctness, thresholds.answer_correctness, True)
        )
    failures = []
    for name, actual, limit, higher_is_better in checks:
        ok = actual >= limit if higher_is_better else actual <= limit
        if not ok:
            bound = "below" if higher_is_better else "above"
            failures.append(f"{name} {actual:.4f} is {bound} the gate {limit:.4f}")
    # Non-leakage is absolute: a scoped question that surfaces an excluded
    # document or revision fails the release regardless of every score above.
    for item_id, leaked in retrieval.leaks:
        failures.append(f"non-leakage violation on {item_id}: leaked {', '.join(leaked)}")
    return tuple(failures)


def force_offline(settings: AppSettings) -> AppSettings:
    """Return settings with external tools forced offline. Evals must never
    depend on live third-party endpoints (openFDA/eCFR): a network outage or
    upstream change would otherwise make a gate flap without any code change.
    Extracted as a pure function so this invariant is asserted in isolation,
    without standing up the retrieval stack."""
    return settings.model_copy(
        update={"external": settings.external.model_copy(update={"offline": True})}
    )


async def run_battery(
    settings: AppSettings,
    items: list[EvalItem],
    *,
    smoke_only: bool = False,
    thresholds: BatteryThresholds = DEFAULT_THRESHOLDS,
    invariants: CoverageInvariants | None = None,
) -> BatteryReport:
    if invariants is None:
        invariants = SMOKE_INVARIANTS if smoke_only else FULL_INVARIANTS
    settings = force_offline(settings)
    engine = create_engine(settings.postgres)
    session_factory = create_session_factory(engine)
    providers = build_providers(settings.providers)
    qdrant_key = settings.qdrant.api_key.get_secret_value() if settings.qdrant.api_key else None
    qdrant = AsyncQdrantClient(url=settings.qdrant.url, api_key=qdrant_key)
    graph_driver = create_graph_driver(settings.neo4j)
    try:
        retriever = HybridRetriever(
            settings=settings,
            qdrant=qdrant,
            session_factory=session_factory,
            embeddings=providers.embeddings,
            reranker=providers.rerank,
        )
        deps = AgentDeps(
            settings=settings,
            retriever=retriever,
            llm=providers.llm,
            llm_is_fake="llm" in providers.using_fakes,
            warehouse=WarehouseTool(session_factory=session_factory, settings=settings),
            graph=GraphWalker(driver=graph_driver, settings=settings),
            external=build_external_toolkit(settings.external),
        )
        agent_graph = build_agent_graph(deps)

        evaluated = [i for i in items if not smoke_only or i.smoke]
        retrieval = await evaluate(retriever, items, smoke_only=smoke_only)
        answers = await evaluate_answers(agent_graph, items, smoke_only=smoke_only)
        noise = await evaluate_noise(retriever, items, smoke_only=smoke_only)
        routing = evaluate_routing(evaluated)
    finally:
        await graph_driver.close()
        await qdrant.close()
        await engine.dispose()
        await providers.aclose()

    failures = gate_failures(retrieval, answers, routing, noise, thresholds) + coverage_failures(
        evaluated, retrieval, noise, invariants, correctness_scored=len(answers.checked())
    )
    return BatteryReport(
        retrieval=retrieval, answers=answers, routing=routing, noise=noise, failures=failures
    )
