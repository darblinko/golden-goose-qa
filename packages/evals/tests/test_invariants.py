"""Coverage invariants: the battery must fail when the QA set shrinks or skews,
independently of the quality scores."""

from gg_evals.invariants import CoverageInvariants, coverage_failures, qa_fingerprint
from gg_evals.noise import NoiseReport, NoiseResult
from gg_evals.retrieval_eval import EvalItem, EvalReport, ItemResult

INV = CoverageInvariants(
    min_items=6,
    min_scored=5,
    max_skip_rate=0.2,
    min_per_pattern=2,
    min_noise_tested=4,
)

PATTERNS = ("procedure_content", "trace_walk", "counts_aggregates")


def _items(n_per_pattern: int) -> list[EvalItem]:
    items = []
    counter = 1
    for pattern in PATTERNS:
        for _ in range(n_per_pattern):
            items.append(
                EvalItem(
                    id=f"QA-{counter:04d}",
                    question="q",
                    pattern=pattern,
                    evidence_doc_ids=["SOP-001"],
                )
            )
            counter += 1
    return items


def _retrieval(n_scored: int, n_skipped: int) -> EvalReport:
    results = tuple(
        ItemResult(
            item_id=f"S-{i}",
            pattern="procedure_content",
            question="q",
            relevant=("SOP-001",),
            ranked=("SOP-001",),
            recall=1.0,
            mrr=1.0,
            ndcg=1.0,
        )
        for i in range(n_scored)
    )
    skipped = {f"K-{i}": "aggregate pseudo-id" for i in range(n_skipped)}
    return EvalReport(results=results, skipped=skipped)


def _noise(n_tested: int) -> NoiseReport:
    return NoiseReport(
        results=tuple(
            NoiseResult(f"N-{i}", "p", recall_clean=1.0, recall_noisy=1.0, intrusion=0.0)
            for i in range(n_tested)
        )
    )


def test_healthy_coverage_passes():
    items = _items(3)  # 9 items, 3 per pattern
    assert coverage_failures(items, _retrieval(8, 1), _noise(6), INV) == ()


def test_too_few_items_fails():
    items = _items(1)  # 3 items, below min_items 6
    failures = coverage_failures(items, _retrieval(3, 0), _noise(4), INV)
    assert any("below the floor 6" in f for f in failures)


def test_thin_pattern_fails():
    items = _items(3)[:-2]  # counts_aggregates now has 1 item, below per-pattern floor 2
    failures = coverage_failures(items, _retrieval(6, 1), _noise(5), INV)
    assert any("counts_aggregates" in f and "per-pattern floor" in f for f in failures)


def test_excessive_skip_rate_fails():
    items = _items(3)  # 9 items; 3 skipped = 0.33 > cap 0.2
    failures = coverage_failures(items, _retrieval(6, 3), _noise(5), INV)
    assert any("skip rate" in f for f in failures)


def test_too_few_scored_fails():
    items = _items(3)
    failures = coverage_failures(items, _retrieval(4, 0), _noise(5), INV)
    assert any("retrieval items scored" in f for f in failures)


def test_too_few_noise_tested_fails():
    items = _items(3)
    failures = coverage_failures(items, _retrieval(8, 1), _noise(2), INV)
    assert any("noise-tested" in f for f in failures)


def test_untested_noise_items_do_not_count_toward_the_floor():
    items = _items(3)
    mixed = NoiseReport(
        results=tuple(
            NoiseResult(f"N-{i}", "p", 1.0, 1.0, 0.0, noise_tested=i < 3) for i in range(8)
        )
    )  # 8 results but only 3 actually tested, below floor 4
    failures = coverage_failures(items, _retrieval(8, 1), mixed, INV)
    assert any("noise-tested" in f for f in failures)


def test_fingerprint_is_stable_and_pinnable():
    items = _items(3)
    pin = qa_fingerprint(items)
    pinned = CoverageInvariants(6, 5, 0.2, 2, 4, pinned_fingerprint=pin)
    assert coverage_failures(items, _retrieval(8, 1), _noise(6), pinned) == ()

    dropped = items[:-1]  # a lost question changes the fingerprint
    failures = coverage_failures(dropped, _retrieval(8, 1), _noise(6), pinned)
    assert any("fingerprint" in f for f in failures)
