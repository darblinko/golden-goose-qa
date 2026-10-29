"""Deterministic routing eval: overrides, default fallback, and scoring."""

from typing import get_args

import pytest
from gg_agents.state import DEFAULT_PATTERN, PATTERNS
from gg_evals.retrieval_eval import EvalItem
from gg_evals.routing_eval import (
    EXPECTED_ROUTES,
    deterministic_route,
    evaluate_routing,
)
from gg_synthdata.qa import Pattern as QAPattern


def _item(
    item_id: str, question: str, pattern: str, expected_routes: list[str] | None = None
) -> EvalItem:
    return EvalItem(
        id=item_id,
        question=question,
        pattern=pattern,
        evidence_doc_ids=["SOP-001"],
        expected_routes=expected_routes or [],
    )


def test_expected_routes_only_name_real_patterns():
    for pattern, routes in EXPECTED_ROUTES.items():
        assert routes, f"{pattern} has an empty acceptable set"
        assert routes <= set(PATTERNS)


def test_expected_routes_cover_every_generator_pattern():
    # evaluate_routing raises on an uncovered pattern, so a new QA pattern
    # without an entry here would fail the nightly battery — catch it in
    # unit tests instead.
    missing = set(get_args(QAPattern)) - set(EXPECTED_ROUTES)
    assert not missing, f"QA patterns without expected routes: {sorted(missing)}"


def test_plain_question_falls_back_to_default():
    assert deterministic_route("What does the procedure say about handling?") == DEFAULT_PATTERN


def test_requirement_id_routes_to_trace():
    assert deterministic_route("Show verification evidence for REQ-023.") == "trace"


def test_count_phrasing_routes_to_aggregate():
    assert deterministic_route("How many CAPAs were opened in 2025?") == "aggregate"


def test_evaluate_routing_scores_acceptable_and_misroutes():
    items = [
        _item("QA-1", "How many complaints were received in 2025?", "counts_aggregates"),
        _item("QA-2", "How many complaints were received in 2025?", "trace_walk"),
    ]
    report = evaluate_routing(items)
    assert report.accuracy == 0.5
    (miss,) = report.misroutes()
    assert miss.item_id == "QA-2" and miss.route == "aggregate"
    assert report.as_dict()["misroutes"] == [
        {"item_id": "QA-2", "pattern": "trace_walk", "route": "aggregate"}
    ]


def test_per_item_expected_routes_override_the_pattern_table():
    # The MRM "how many CAPAs" question routes to aggregate; a governance_clinical
    # item that expects only `record` (as the generator emits) is a misroute,
    # even though the pattern table historically tolerated aggregate.
    item = _item(
        "QA-1",
        "What period did management review MRM-2025-01 cover, and how many CAPAs?",
        "governance_clinical",
        expected_routes=["record"],
    )
    report = evaluate_routing([item])
    assert report.accuracy == 0.0
    assert report.misroutes()[0].route == "aggregate"


def test_per_item_routes_are_trusted_even_when_the_pattern_is_unknown():
    # A carried expected_routes list means no lookup in the pattern table.
    item = _item("QA-1", "How many CAPAs were opened in 2025?", "novel", ["aggregate"])
    report = evaluate_routing([item])
    assert report.accuracy == 1.0


def test_unknown_qa_pattern_without_per_item_routes_is_an_error_not_a_skip():
    with pytest.raises(ValueError, match="no expected routes"):
        evaluate_routing([_item("QA-1", "Anything", "brand_new_pattern")])


def test_empty_items_scores_zero():
    assert evaluate_routing([]).accuracy == 0.0
