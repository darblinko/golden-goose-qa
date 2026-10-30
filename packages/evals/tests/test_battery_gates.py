"""Battery gate logic (pure — the full battery runs in integration tests)."""

from gg_common.settings import AppSettings, ExternalToolSettings
from gg_evals.answer_eval import AnswerReport, AnswerResult
from gg_evals.battery import BatteryThresholds, force_offline, gate_failures
from gg_evals.noise import NoiseReport, NoiseResult
from gg_evals.retrieval_eval import EvalReport, ItemResult
from gg_evals.routing_eval import RoutingReport, RoutingResult


def _retrieval(recall: float, leaked: tuple[str, ...] = ()) -> EvalReport:
    return EvalReport(
        results=(
            ItemResult(
                item_id="QA-1",
                pattern="p",
                question="q",
                relevant=("SOP-001",),
                ranked=("SOP-001",),
                recall=recall,
                mrr=recall,
                ndcg=recall,
                leaked=leaked,
            ),
        )
    )


def _answers(
    grounded: bool,
    support: float,
    citation_precision: float = 1.0,
    citation_recall: float = 1.0,
    correct: bool | None = None,
) -> AnswerReport:
    return AnswerReport(
        results=(
            AnswerResult(
                item_id="QA-1",
                pattern="p",
                verdict="grounded" if grounded else "insufficient_evidence",
                grounded=grounded,
                citation_precision=citation_precision,
                citation_recall=citation_recall,
                support=support,
                correct=correct,
            ),
        ),
        skipped={},
    )


def _routing(acceptable: bool) -> RoutingReport:
    return RoutingReport(
        results=(RoutingResult(item_id="QA-1", pattern="p", route="record", acceptable=acceptable),)
    )


def _noise(degradation: float) -> NoiseReport:
    return NoiseReport(
        results=(
            NoiseResult(
                item_id="QA-1",
                pattern="p",
                recall_clean=1.0,
                recall_noisy=1.0 - degradation,
                intrusion=0.0,
            ),
        )
    )


THRESHOLDS = BatteryThresholds()


def test_force_offline_disables_live_external_tools():
    # R-13: the battery must never reach live third-party endpoints. Even when
    # the environment leaves external tools online, the battery run forces them
    # offline, and does so without disturbing the other external settings.
    settings = AppSettings(external=ExternalToolSettings(offline=False, result_limit=7))
    forced = force_offline(settings)
    assert forced.external.offline is True
    assert forced.external.result_limit == 7  # unrelated settings preserved
    assert settings.external.offline is False  # original left unmutated


def test_all_gates_pass():
    failures = gate_failures(
        _retrieval(0.9), _answers(True, 0.8), _routing(True), _noise(0.0), THRESHOLDS
    )
    assert failures == ()


def test_each_gate_fails_independently():
    assert (
        "retrieval recall"
        in gate_failures(
            _retrieval(0.5), _answers(True, 0.8), _routing(True), _noise(0.0), THRESHOLDS
        )[0]
    )
    assert (
        "grounded rate"
        in gate_failures(
            _retrieval(0.9), _answers(False, 0.8), _routing(True), _noise(0.0), THRESHOLDS
        )[0]
    )
    assert (
        "routing accuracy"
        in gate_failures(
            _retrieval(0.9), _answers(True, 0.8), _routing(False), _noise(0.0), THRESHOLDS
        )[0]
    )
    assert (
        "noise degradation"
        in gate_failures(
            _retrieval(0.9), _answers(True, 0.8), _routing(True), _noise(0.5), THRESHOLDS
        )[0]
    )


def test_low_support_on_grounded_answer_fails_support_gate():
    failures = gate_failures(
        _retrieval(0.9), _answers(True, 0.1), _routing(True), _noise(0.0), THRESHOLDS
    )
    assert len(failures) == 1 and "answer support" in failures[0]


def test_low_citation_metrics_fail_their_own_gates():
    prec = gate_failures(
        _retrieval(0.9),
        _answers(True, 0.8, citation_precision=0.1),
        _routing(True),
        _noise(0.0),
        THRESHOLDS,
    )
    assert len(prec) == 1 and "citation precision" in prec[0]
    rec = gate_failures(
        _retrieval(0.9),
        _answers(True, 0.8, citation_recall=0.1),
        _routing(True),
        _noise(0.0),
        THRESHOLDS,
    )
    assert len(rec) == 1 and "citation recall" in rec[0]


def test_failures_name_the_gate_value_and_bound():
    (failure,) = gate_failures(
        _retrieval(0.5), _answers(True, 0.8), _routing(True), _noise(0.0), THRESHOLDS
    )
    assert "0.5000" in failure and "below" in failure and "0.8000" in failure


def test_leak_blocks_release_despite_passing_scores():
    # Every scalar gate passes, but a scoped question surfaced an excluded
    # document. Non-leakage is absolute: the release still fails.
    failures = gate_failures(
        _retrieval(0.9, leaked=("SOP-006", "SOP-004@B")),
        _answers(True, 0.8),
        _routing(True),
        _noise(0.0),
        THRESHOLDS,
    )
    assert len(failures) == 1
    assert "non-leakage violation on QA-1" in failures[0]
    assert "SOP-006" in failures[0] and "SOP-004@B" in failures[0]


def test_wrong_task_answer_fails_correctness_gate():
    failures = gate_failures(
        _retrieval(0.9), _answers(True, 0.8, correct=False), _routing(True), _noise(0.0), THRESHOLDS
    )
    assert len(failures) == 1 and "answer correctness" in failures[0]


def test_correctness_gate_needs_checked_items():
    # A run with no task-checkable items has nothing to gate.
    failures = gate_failures(
        _retrieval(0.9), _answers(True, 0.8), _routing(True), _noise(0.0), THRESHOLDS
    )
    assert failures == ()
