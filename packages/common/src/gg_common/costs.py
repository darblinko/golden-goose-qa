"""Cost telemetry: token usage per pipeline stage and per conversation.

Provider adapters call record_usage() with what they know (provider, model,
token counts from the API response; fakes estimate at four characters per
token). The pipeline stage comes from an ambient cost_stage() label set at
call sites, and events land on the ledger installed by track_costs() for the
current task — no ledger, no recording, never an error. Both contexts are
contextvars, so concurrent conversations keep separate ledgers.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

# Estimated public list prices in USD per million tokens (input, output),
# current as of 2026-07. Matching is by model-name prefix; unknown models
# price at zero — token counts still record, so telemetry never blocks on a
# stale price table.
_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (1.0, 5.0),
    "claude-opus": (5.0, 25.0),
    "voyage-4": (0.18, 0.0),
    "rerank-2.5": (0.05, 0.0),
    "gemini-3-flash": (0.30, 2.50),
}

CHARS_PER_TOKEN_ESTIMATE = 4


@dataclass(frozen=True)
class UsageEvent:
    stage: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class CostLedger:
    """Accumulates usage events for one unit of work (a chat turn, an ingest
    run). Create via track_costs(); read via events / summary()."""

    def __init__(self) -> None:
        self._events: list[UsageEvent] = []

    @property
    def events(self) -> tuple[UsageEvent, ...]:
        return tuple(self._events)

    def record(
        self,
        *,
        stage: str,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self._events.append(
            UsageEvent(
                stage=stage,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=_cost_usd(model, input_tokens, output_tokens),
            )
        )

    def summary(self) -> dict[str, Any]:
        by_stage: dict[str, dict[str, float | int]] = {}
        for event in self._events:
            stage = by_stage.setdefault(
                event.stage, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            )
            stage["input_tokens"] += event.input_tokens
            stage["output_tokens"] += event.output_tokens
            stage["cost_usd"] = round(float(stage["cost_usd"]) + event.cost_usd, 6)
        return {
            "input_tokens": sum(e.input_tokens for e in self._events),
            "output_tokens": sum(e.output_tokens for e in self._events),
            "cost_usd": round(sum(e.cost_usd for e in self._events), 6),
            "by_stage": by_stage,
        }


_ledger: ContextVar[CostLedger | None] = ContextVar("gg_cost_ledger", default=None)
_stage: ContextVar[str] = ContextVar("gg_cost_stage", default="unlabeled")


@contextmanager
def track_costs() -> Iterator[CostLedger]:
    """Install a fresh ledger for the enclosed block (task-local)."""
    ledger = CostLedger()
    token = _ledger.set(ledger)
    try:
        yield ledger
    finally:
        _ledger.reset(token)


@contextmanager
def cost_stage(name: str) -> Iterator[None]:
    """Label usage recorded in the enclosed block with a pipeline stage."""
    token = _stage.set(name)
    try:
        yield
    finally:
        _stage.reset(token)


def record_usage(
    *, provider: str, model: str, input_tokens: int = 0, output_tokens: int = 0
) -> None:
    """Record usage against the active ledger; a no-op when none is active."""
    ledger = _ledger.get()
    if ledger is None:
        return
    ledger.record(
        stage=_stage.get(),
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def estimate_tokens(text: str) -> int:
    """Rough token estimate for fake providers, so offline runs still show
    the cost shape of a turn."""
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE) if text else 0


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    for prefix, (input_rate, output_rate) in _PRICES_PER_MTOK.items():
        if model.startswith(prefix):
            return round(
                input_tokens / 1_000_000 * input_rate + output_tokens / 1_000_000 * output_rate,
                6,
            )
    return 0.0
