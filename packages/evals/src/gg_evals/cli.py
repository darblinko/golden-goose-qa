"""Eval CLI.

    gg-eval retrieval --qa data/synthetic/qa/smoke_qa.json --gate 0.8
    gg-eval battery --qa data/synthetic/qa/smoke_qa.json \
        --history evals/history.jsonl --dashboard evals/dashboard.html

`retrieval` scores the retriever alone; `battery` runs the full stack —
retrieval, end-to-end answers through the agent graph, routing, and reranker
noise sensitivity — appends the run to a JSONL history, and renders the trend
dashboard. Exit code is nonzero when any gate fails — CI treats a quality
regression as a build failure.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from gg_common.db import create_engine, create_session_factory
from gg_common.logging import configure_logging
from gg_common.providers.factory import build_providers
from gg_common.settings import get_settings
from gg_retrieval.retriever import HybridRetriever
from qdrant_client import AsyncQdrantClient

from gg_evals.battery import BatteryReport, BatteryThresholds, run_battery
from gg_evals.dashboard import render_dashboard
from gg_evals.history import (
    append_history,
    current_git_sha,
    load_history,
    make_record,
    overwrite_history,
    prune_incomparable,
)
from gg_evals.retrieval_eval import EvalItem, EvalReport, K, evaluate

DEFAULT_GATE = 0.8


def load_items(qa_path: Path) -> list[EvalItem]:
    data = json.loads(qa_path.read_text())
    raw_items = data["items"] if isinstance(data, dict) else data
    return [EvalItem.model_validate(item) for item in raw_items]


def load_schema_version(qa_path: Path) -> int | None:
    """The QA set's schema_version, used to stamp the run and to reject a
    restored trend built from an incompatible golden set."""
    data = json.loads(qa_path.read_text())
    version = data.get("schema_version") if isinstance(data, dict) else None
    return version if isinstance(version, int) else None


async def _run(qa_path: Path, *, smoke_only: bool, gate: float, out: Path | None) -> int:
    settings = get_settings()
    providers = build_providers(settings.providers)
    engine = create_engine(settings.postgres)
    api_key = settings.qdrant.api_key.get_secret_value() if settings.qdrant.api_key else None
    qdrant = AsyncQdrantClient(url=settings.qdrant.url, api_key=api_key)
    try:
        retriever = HybridRetriever(
            settings=settings,
            qdrant=qdrant,
            session_factory=create_session_factory(engine),
            embeddings=providers.embeddings,
            reranker=providers.rerank,
        )
        report = await evaluate(retriever, load_items(qa_path), smoke_only=smoke_only)
    finally:
        await qdrant.close()
        await engine.dispose()

    _print_report(report, using_fakes=providers.using_fakes)
    if out is not None:
        out.write_text(json.dumps(report.as_dict(), indent=1))
        print(f"report written to {out}")
    if not report.results:
        print("no evaluable items — nothing was scored", file=sys.stderr)
        return 1
    if report.recall < gate:
        print(f"GATE FAILED: recall@{K} {report.recall:.3f} < {gate}", file=sys.stderr)
        return 1
    print(f"gate passed: recall@{K} {report.recall:.3f} >= {gate}")
    return 0


def _print_report(report: EvalReport, *, using_fakes: tuple[str, ...]) -> None:
    print(
        f"evaluated {len(report.results)} items "
        f"(skipped {len(report.skipped)} unretrievable): "
        f"recall@{K}={report.recall:.3f} mrr@{K}={report.mrr:.3f} ndcg@{K}={report.ndcg:.3f}"
    )
    for pattern, stats in report.by_pattern().items():
        print(
            f"  {pattern}: n={int(stats['n'])} recall={stats['recall']:.3f} mrr={stats['mrr']:.3f}"
        )
    for item_id, reason in report.skipped.items():
        print(f"  skipped {item_id}: {reason}")
    if using_fakes:
        print(f"NOTE: fake providers in use for: {', '.join(using_fakes)}")
    misses = [r for r in report.results if r.recall < 1.0]
    for miss in misses:
        print(
            f"  MISS {miss.item_id} ({miss.pattern}): wanted {list(miss.relevant)}, "
            f"got {list(miss.ranked)[:5]}",
            file=sys.stderr,
        )


async def _run_battery(args: argparse.Namespace) -> int:
    thresholds = BatteryThresholds(
        recall=args.gate_recall,
        grounded_rate=args.gate_grounded,
        support=args.gate_support,
        routing_accuracy=args.gate_routing,
        max_noise_degradation=args.gate_noise,
    )
    report = await run_battery(
        get_settings(), load_items(args.qa), smoke_only=args.smoke, thresholds=thresholds
    )
    _print_battery(report)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report.as_dict(), indent=1))
        print(f"report written to {args.out}")
    if args.history is not None:
        schema_version = load_schema_version(args.qa)
        kept, dropped = prune_incomparable(load_history(args.history), schema_version)
        if dropped:
            overwrite_history(args.history, kept)
            print(
                f"pruned {len(dropped)} stale history record(s) that did not match "
                f"QA schema_version={schema_version}; trend restarts from comparable runs",
                file=sys.stderr,
            )
        record = make_record(
            report.as_dict(),
            smoke=args.smoke,
            git_sha=current_git_sha(),
            schema_version=schema_version,
        )
        append_history(args.history, record)
        print(f"history appended to {args.history}")
        if args.dashboard is not None:
            args.dashboard.parent.mkdir(parents=True, exist_ok=True)
            args.dashboard.write_text(render_dashboard(load_history(args.history)))
            print(f"dashboard written to {args.dashboard}")

    if not report.retrieval.results or not report.answers.results:
        print("no evaluable items — nothing was scored", file=sys.stderr)
        return 1
    if report.failures:
        for failure in report.failures:
            print(f"GATE FAILED: {failure}", file=sys.stderr)
        return 1
    print("all gates passed")
    return 0


def _print_battery(report: BatteryReport) -> None:
    r, a, n = report.retrieval, report.answers, report.noise
    print(
        f"retrieval: n={len(r.results)} recall@{K}={r.recall:.3f} "
        f"mrr@{K}={r.mrr:.3f} ndcg@{K}={r.ndcg:.3f}"
    )
    print(
        f"answers: n={len(a.results)} grounded_rate={a.grounded_rate:.3f} "
        f"citation_precision={a.citation_precision:.3f} "
        f"citation_recall={a.citation_recall:.3f} support={a.support:.3f}"
    )
    for miss in a.ungrounded():
        print(f"  UNGROUNDED {miss.item_id} ({miss.pattern}): verdict={miss.verdict}")
    print(f"routing: n={len(report.routing.results)} accuracy={report.routing.accuracy:.3f}")
    for misroute in report.routing.misroutes():
        print(f"  MISROUTE {misroute.item_id} ({misroute.pattern}) -> {misroute.route}")
    print(
        f"noise: n={len(n.results)} clean={n.recall_clean:.3f} noisy={n.recall_noisy:.3f} "
        f"degradation={n.degradation:.3f} intrusion={n.intrusion:.3f}"
    )


def main() -> int:
    configure_logging(get_settings())
    parser = argparse.ArgumentParser(prog="gg-eval")
    sub = parser.add_subparsers(dest="command", required=True)

    retrieval = sub.add_parser("retrieval", help="score retrieval against a golden QA file")
    retrieval.add_argument("--qa", type=Path, required=True)
    retrieval.add_argument("--smoke", action="store_true", help="only items marked smoke")
    retrieval.add_argument("--gate", type=float, default=DEFAULT_GATE)
    retrieval.add_argument("--out", type=Path, default=None, help="write JSON report here")

    battery = sub.add_parser("battery", help="run the full eval battery with gates")
    battery.add_argument("--qa", type=Path, required=True)
    battery.add_argument("--smoke", action="store_true", help="only items marked smoke")
    battery.add_argument("--out", type=Path, default=None, help="write JSON report here")
    battery.add_argument("--history", type=Path, default=None, help="append run to this JSONL")
    battery.add_argument(
        "--dashboard", type=Path, default=None, help="render trend HTML here (needs --history)"
    )
    battery.add_argument("--gate-recall", type=float, default=BatteryThresholds.recall)
    battery.add_argument("--gate-grounded", type=float, default=BatteryThresholds.grounded_rate)
    battery.add_argument("--gate-support", type=float, default=BatteryThresholds.support)
    battery.add_argument("--gate-routing", type=float, default=BatteryThresholds.routing_accuracy)
    battery.add_argument(
        "--gate-noise", type=float, default=BatteryThresholds.max_noise_degradation
    )

    args = parser.parse_args()
    if not args.qa.is_file():
        print(f"QA file not found: {args.qa}", file=sys.stderr)
        return 2
    if args.command == "battery":
        return asyncio.run(_run_battery(args))
    return asyncio.run(_run(args.qa, smoke_only=args.smoke, gate=args.gate, out=args.out))


if __name__ == "__main__":
    raise SystemExit(main())
