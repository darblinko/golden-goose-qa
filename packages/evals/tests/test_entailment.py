"""Lexical sentence-support scoring and its adversarial guards."""

import pytest
from gg_evals.entailment import _entails, cited_sentence_support, sentence_support

EVIDENCE = [
    "Effectiveness verification is required within 90 days of CAPA closure.",
    "The quality manager approves all corrective action plans before implementation.",
]


def test_fully_supported_answer_scores_one():
    answer = "Effectiveness verification is required within 90 days of closure. [1]"
    assert sentence_support(answer, EVIDENCE) == 1.0


def test_fabricated_sentence_lowers_support():
    answer = (
        "Effectiveness verification is required within 90 days of closure. "
        "Sterilization cycles must run at 134 degrees celsius for laparoscopic instruments."
    )
    score = sentence_support(answer, EVIDENCE)
    assert 0.0 < score < 1.0


def test_best_evidence_wins_per_sentence():
    # Each sentence is covered by a different evidence text; both should score
    # against their best match, not a single merged one.
    answer = (
        "Effectiveness verification is required within 90 days. "
        "The quality manager approves all corrective action plans."
    )
    assert sentence_support(answer, EVIDENCE) == 1.0


def test_no_evidence_scores_zero():
    assert sentence_support("Any answer at all with several words here.", []) == 0.0


def test_short_fragments_are_not_scored():
    # "Yes. [1]" has too few content tokens to judge either way.
    assert sentence_support("Yes. [1]", EVIDENCE) == 0.0


def test_citation_markers_are_stripped_before_scoring():
    with_markers = "Effectiveness verification is required within 90 days of closure. [1][2]"
    without = "Effectiveness verification is required within 90 days of closure."
    assert sentence_support(with_markers, EVIDENCE) == sentence_support(without, EVIDENCE)


# --- Adversarial guards: a supported claim and its tampered twin ---------------


def test_wrong_number_is_penalized_below_the_true_number():
    # The true window says "within 90 days"; asserting 30 days shares every word
    # but the number the evidence does not contain, and must not score as
    # supported.
    supported = "Effectiveness verification is required within 90 days of closure."
    tampered = "Effectiveness verification is required within 30 days of closure."
    assert sentence_support(supported, EVIDENCE) == 1.0
    assert sentence_support(tampered, EVIDENCE) < 0.5


def test_added_negation_flips_support_down():
    # "the quality manager approves" vs "never approves": near-identical tokens,
    # opposite meaning. The polarity flip alone collapses the score.
    supported = "The quality manager approves all corrective action plans."
    negated = "The quality manager never approves corrective action plans."
    assert sentence_support(supported, EVIDENCE) == 1.0
    assert sentence_support(negated, EVIDENCE) < 0.5


def test_negation_penalty_only_fires_above_the_coverage_gate():
    evidence_text = "The quality manager approves all corrective action plans."
    # High coverage + a polarity flip → treated as a contradiction.
    penalized = _entails(
        "The quality manager never approves corrective action plans.", evidence_text
    )
    assert penalized < 0.3
    # Below the coverage gate the negation is ignored: only two of five tokens
    # overlap, so the score stays at that 0.4 coverage rather than collapsing to
    # 0.08 — a loosely related sentence that merely contains "not" is not a
    # contradiction of evidence it barely touches.
    below_gate = _entails("Quality not approves shipping labels.", evidence_text)
    assert below_gate == pytest.approx(0.4)


@pytest.mark.xfail(
    reason="lexical coverage cannot tell 'A approves B' from 'B approves A'; "
    "actor-swap detection is the LLM-NLI seam's job (ADR 0019)",
    strict=True,
)
def test_actor_swap_is_detected():
    # Same token set, reversed roles: the approver and the plan swap places.
    # This documents the known gap — flip it to a normal test when NLI lands.
    evidence = ["The quality manager approves the supplier corrective action plan."]
    swapped = "The supplier corrective action plan approves the quality manager."
    assert sentence_support(swapped, evidence) < 0.5


# --- cited_sentence_support: score against the source the sentence cites -------


def test_cited_support_scores_against_the_cited_source_only():
    # [1] is the effectiveness line, [2] is the approver line.
    right = "Effectiveness verification is required within 90 days of closure. [1]"
    assert cited_sentence_support(right, EVIDENCE) == 1.0
    # Same true sentence, but citing [2] (the approver line, which does not
    # support it). The correct source at [1] no longer rescues the score...
    wrong = "Effectiveness verification is required within 90 days of closure. [2]"
    assert cited_sentence_support(wrong, EVIDENCE) < 0.5
    # ...whereas marker-agnostic sentence_support still finds it in the window.
    assert sentence_support(wrong, EVIDENCE) == 1.0


def test_cited_support_falls_back_to_the_window_for_uncited_sentences():
    answer = "Effectiveness verification is required within 90 days of closure."
    assert cited_sentence_support(answer, EVIDENCE) == 1.0


def test_out_of_range_citation_marker_scores_as_unsupported():
    # [9] points past the window. A sentence whose only marker is invalid cites
    # nothing that exists, so unrelated evidence elsewhere must not rescue it.
    answer = "Effectiveness verification is required within 90 days of closure. [9]"
    assert cited_sentence_support(answer, EVIDENCE) == 0.0


def test_exact_evidence_sentence_with_invalid_marker_gets_no_credit():
    answer = "Effectiveness verification is required within 90 days of closure. [999]"
    assert cited_sentence_support(answer, EVIDENCE) == 0.0


def test_valid_marker_still_scores_beside_an_invalid_one():
    answer = "Effectiveness verification is required within 90 days of closure. [1][999]"
    assert cited_sentence_support(answer, EVIDENCE) == 1.0
