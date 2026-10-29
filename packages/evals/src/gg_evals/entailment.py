"""Citation entailment: is the answer actually supported by cited evidence?

Hand-rolled lexical support scoring (ADR 0013 precedent, extended in ADR
0019): each answer sentence is checked against evidence text, and the sentence
scores the best single-text coverage of its content tokens. This is
deliberately not an LLM judge — it runs identically in keyless CI and with real
providers, and a fabricated number or entity lowers the score no matter which
provider produced it.

Plain token coverage cannot tell "within 90 days" from "within 30 days" or
"the manager approves" from "the manager does not approve" — a fabricated
number or a flipped polarity shares almost every token. `_entails` (the
single-claim/single-source seam an LLM NLI model would replace) therefore
multiplies coverage by a number-agreement and a negation-agreement factor, so
an adversarial number or negation edit drops the score decisively.
`cited_sentence_support` goes further and scores each sentence only against the
sources its [n] markers point at, so citing the wrong document is not masked by
a correct document elsewhere in the window.
"""

import re

from gg_common.sparse import tokenize

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_MARKER_RE = re.compile(r"\[(\d+)\]")
# A marker written after the sentence's terminal punctuation ("...closure. [2]")
# would otherwise split off as its own fragment and read as uncited; pull it
# back inside the sentence ("...closure[2].") before splitting.
_TRAILING_MARKER_RE = re.compile(r"([.!?])(\s*)((?:\[\d+\])+)")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:e-?\d+)?%?", re.IGNORECASE)
_NEGATION_RE = re.compile(
    r"\b(?:not|no|never|without|cannot|none|neither|nor|fails?|unable|absent|lacks?|"
    r"excludes?|non-reportable)\b|n't\b",
    re.IGNORECASE,
)
_MIN_CONTENT_TOKENS = 4

# A claim that asserts a number or a polarity the evidence does not is
# unsupported even when the surrounding words overlap; these factors collapse
# the coverage score rather than nudging it.
_NUMBER_MISMATCH_FACTOR = 0.2
_NEGATION_MISMATCH_FACTOR = 0.2
# Only treat a polarity flip as a contradiction when the claim otherwise closely
# matches the evidence — a low-overlap paraphrase that happens to differ in a
# stray "no" is not a contradiction, and penalizing it would punish paraphrase.
_NEGATION_COVERAGE_GATE = 0.6


def _numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text.lower()))


def _is_negated(text: str) -> bool:
    return _NEGATION_RE.search(text) is not None


def _entails(claim: str, evidence_text: str) -> float:
    """Coverage of the claim's content tokens by one evidence text, discounted
    for a number or a negation the evidence does not support. This is the seam a
    provider-backed NLI judge would replace (ADR 0019)."""
    claim_tokens = set(tokenize(claim))
    if not claim_tokens:
        return 0.0
    evidence_tokens = frozenset(tokenize(evidence_text))
    coverage = len(claim_tokens & evidence_tokens) / len(claim_tokens)

    claim_numbers = _numbers(claim)
    if claim_numbers and not claim_numbers <= _numbers(evidence_text):
        coverage *= _NUMBER_MISMATCH_FACTOR

    if coverage >= _NEGATION_COVERAGE_GATE and _is_negated(claim) != _is_negated(evidence_text):
        coverage *= _NEGATION_MISMATCH_FACTOR

    return coverage


def _scoreable(sentence: str) -> bool:
    return len(set(tokenize(sentence))) >= _MIN_CONTENT_TOKENS


def sentence_support(answer: str, evidence_texts: list[str]) -> float:
    """Mean over scoreable sentences of the best single-evidence entailment of
    that sentence. 1.0 = every sentence fully supported by at least one evidence
    text; 0.0 = no overlap or no evidence. Marker-agnostic: a sentence may be
    supported by any evidence text in the window."""
    if not evidence_texts:
        return 0.0
    scores: list[float] = []
    for sentence in _SENTENCE_SPLIT_RE.split(_MARKER_RE.sub("", answer)):
        if not _scoreable(sentence):
            continue
        scores.append(max(_entails(sentence, evidence) for evidence in evidence_texts))
    return sum(scores) / len(scores) if scores else 0.0


def _cited_indices(sentence: str, n_sources: int) -> list[int]:
    """Zero-based evidence indices a sentence's [n] markers point at, in range."""
    seen: list[int] = []
    for marker in _MARKER_RE.findall(sentence):
        index = int(marker) - 1
        if 0 <= index < n_sources and index not in seen:
            seen.append(index)
    return seen


def cited_sentence_support(answer: str, evidence_texts: list[str]) -> float:
    """Like sentence_support, but each sentence is scored only against the
    sources its own [n] markers cite (falling back to the whole window when a
    sentence carries no marker). Citing the wrong document then lowers support
    even if the right document sits elsewhere in the window."""
    if not evidence_texts:
        return 0.0
    normalized = _TRAILING_MARKER_RE.sub(r"\3\1", answer)
    scores: list[float] = []
    for raw_sentence in _SENTENCE_SPLIT_RE.split(normalized):
        indices = _cited_indices(raw_sentence, len(evidence_texts))
        sentence = _MARKER_RE.sub("", raw_sentence)
        if not _scoreable(sentence):
            continue
        sources = [evidence_texts[i] for i in indices] if indices else evidence_texts
        scores.append(max(_entails(sentence, source) for source in sources))
    return sum(scores) / len(scores) if scores else 0.0
