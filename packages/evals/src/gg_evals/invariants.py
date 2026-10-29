"""Battery coverage invariants — guardrails that stop a gate passing by
shrinking its own denominator.

The recall, grounded, routing, and noise gates all average over the items that
survive selection. Without a floor on how many items survive, how they spread
across audit patterns, and how many are actually noise-tested, a QA set that
quietly loses questions leaves every gate green. These invariants
fail the battery when coverage itself regresses, independently of the scores.
"""

import hashlib
from collections import Counter
from dataclasses import dataclass

from gg_evals.noise import NoiseReport
from gg_evals.retrieval_eval import EvalItem, EvalReport


@dataclass(frozen=True)
class CoverageInvariants:
    min_items: int  # total QA items in the set
    min_scored: int  # retrieval items that must enter the recall denominator
    max_skip_rate: float  # fraction of items allowed to be non-retrievable skips
    min_per_pattern: int  # every audit pattern needs this much real coverage
    min_noise_tested: int  # items that must actually face distractors
    pinned_fingerprint: str | None = None  # when set, QA structure must match exactly


# The full golden set (currently 215 items across 12 patterns, 9 aggregate
# skips). Floors sit comfortably below current coverage so an ordinary edit
# passes, but a materially shrunk or lopsided set fails.
FULL_INVARIANTS = CoverageInvariants(
    min_items=200,
    min_scored=180,
    max_skip_rate=0.08,
    min_per_pattern=5,
    min_noise_tested=150,
)

# The smoke subset (currently ~34 items after every pattern is represented).
SMOKE_INVARIANTS = CoverageInvariants(
    min_items=30,
    min_scored=24,
    max_skip_rate=0.15,
    min_per_pattern=1,
    min_noise_tested=20,
)


def qa_fingerprint(items: list[EvalItem]) -> str:
    """Stable structural hash of the QA set: ids, patterns, and evidence — not
    answer text, so wording fixes do not churn the pin while a dropped or
    re-pointed question does."""
    payload = sorted((i.id, i.pattern, tuple(sorted(i.evidence_doc_ids))) for i in items)
    return hashlib.sha256(repr(payload).encode()).hexdigest()


def coverage_failures(
    items: list[EvalItem],
    retrieval: EvalReport,
    noise: NoiseReport,
    invariants: CoverageInvariants,
) -> tuple[str, ...]:
    failures: list[str] = []
    n_items = len(items)
    if n_items < invariants.min_items:
        failures.append(f"QA set has {n_items} items, below the floor {invariants.min_items}")

    scored = len(retrieval.results)
    if scored < invariants.min_scored:
        failures.append(
            f"only {scored} retrieval items scored, below the floor {invariants.min_scored}"
        )

    skip_rate = len(retrieval.skipped) / n_items if n_items else 1.0
    if skip_rate > invariants.max_skip_rate:
        failures.append(
            f"retrieval skip rate {skip_rate:.4f} exceeds the cap {invariants.max_skip_rate:.4f}"
        )

    for pattern, count in sorted(Counter(i.pattern for i in items).items()):
        if count < invariants.min_per_pattern:
            failures.append(
                f"pattern {pattern!r} has {count} items, "
                f"below the per-pattern floor {invariants.min_per_pattern}"
            )

    tested = len(noise.tested)
    if tested < invariants.min_noise_tested:
        failures.append(
            f"only {tested} items were noise-tested, below the floor {invariants.min_noise_tested}"
        )

    if invariants.pinned_fingerprint is not None:
        actual = qa_fingerprint(items)
        if actual != invariants.pinned_fingerprint:
            failures.append(
                f"QA fingerprint {actual[:12]} does not match the pin "
                f"{invariants.pinned_fingerprint[:12]}"
            )

    return tuple(failures)
