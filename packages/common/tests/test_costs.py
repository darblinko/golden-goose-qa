"""Cost telemetry: ledger aggregation, pricing, and contextvar isolation."""

import asyncio
from typing import Any

from gg_common.costs import (
    CostLedger,
    cost_stage,
    estimate_tokens,
    record_usage,
    track_costs,
)
from gg_common.providers.base import ChatMessage
from gg_common.providers.fakes import (
    FakeEmbeddingProvider,
    FakeLLMProvider,
    FakeRerankProvider,
)


def test_ledger_aggregates_by_stage():
    ledger = CostLedger()
    ledger.record(
        stage="agent.route", provider="anthropic", model="claude-haiku-4-5", input_tokens=1000
    )
    ledger.record(
        stage="agent.generate",
        provider="anthropic",
        model="claude-sonnet-5",
        input_tokens=2000,
        output_tokens=500,
    )
    ledger.record(
        stage="agent.generate",
        provider="anthropic",
        model="claude-sonnet-5",
        input_tokens=1000,
        output_tokens=100,
    )
    summary = ledger.summary()
    assert summary["input_tokens"] == 4000
    assert summary["output_tokens"] == 600
    assert set(summary["by_stage"]) == {"agent.route", "agent.generate"}
    generate = summary["by_stage"]["agent.generate"]
    assert generate["input_tokens"] == 3000
    assert generate["output_tokens"] == 600
    assert summary["cost_usd"] > 0


def test_prices_match_by_model_prefix():
    ledger = CostLedger()
    ledger.record(
        stage="s",
        provider="anthropic",
        model="claude-sonnet-5-20260115",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert ledger.events[0].cost_usd == 18.0  # 3 in + 15 out per MTok


def test_unknown_model_costs_zero_but_tokens_count():
    ledger = CostLedger()
    ledger.record(stage="s", provider="x", model="mystery-model", input_tokens=5000)
    assert ledger.events[0].cost_usd == 0.0
    summary = ledger.summary()
    assert summary["input_tokens"] == 5000
    assert summary["cost_usd"] == 0.0


def test_record_usage_without_ledger_is_a_noop():
    record_usage(provider="anthropic", model="claude-sonnet-5", input_tokens=100)


def test_stage_label_defaults_nests_and_restores():
    with track_costs() as ledger:
        record_usage(provider="p", model="m", input_tokens=1)
        with cost_stage("outer"):
            record_usage(provider="p", model="m", input_tokens=1)
            with cost_stage("inner"):
                record_usage(provider="p", model="m", input_tokens=1)
            record_usage(provider="p", model="m", input_tokens=1)
        record_usage(provider="p", model="m", input_tokens=1)
    stages = [event.stage for event in ledger.events]
    assert stages == ["unlabeled", "outer", "inner", "outer", "unlabeled"]


async def test_ledgers_isolate_across_concurrent_tasks():
    async def work(stage: str, tokens: int) -> dict[str, Any]:
        with track_costs() as ledger:
            with cost_stage(stage):
                record_usage(provider="p", model="m", input_tokens=tokens)
                await asyncio.sleep(0)
                record_usage(provider="p", model="m", input_tokens=tokens)
            return ledger.summary()

    first, second = await asyncio.gather(work("a", 10), work("b", 100))
    assert first["input_tokens"] == 20
    assert set(first["by_stage"]) == {"a"}
    assert second["input_tokens"] == 200
    assert set(second["by_stage"]) == {"b"}


async def test_fake_providers_record_estimated_usage():
    with track_costs() as ledger:
        llm = FakeLLMProvider()
        await llm.complete([ChatMessage(role="user", content="x" * 40)])
        embeddings = FakeEmbeddingProvider(dimensions=8)
        await embeddings.embed_documents(["y" * 40, "z" * 40])
        await embeddings.embed_query("q" * 40)
        reranker = FakeRerankProvider()
        await reranker.rerank("query terms", ["doc one", "doc two"], top_k=1)

    assert len(ledger.events) == 4
    assert all(event.provider == "fake" for event in ledger.events)
    llm_event = ledger.events[0]
    assert llm_event.input_tokens == 10  # 40 chars at 4 chars/token
    assert llm_event.output_tokens >= 1
    embed_event = ledger.events[1]
    assert embed_event.input_tokens == 20  # two 40-char documents
    assert ledger.summary()["cost_usd"] == 0.0  # fake models have no price


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("ab") == 1  # short text never rounds to zero
    assert estimate_tokens("x" * 400) == 100
