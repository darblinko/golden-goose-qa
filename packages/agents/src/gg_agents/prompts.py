"""Prompt builders. Kept as plain functions returning message lists so tests
can assert on exact prompt content and the audit log can hash what was sent."""

from typing import Any

from gg_common.providers.base import ChatMessage

from gg_agents.state import PATTERNS

_CONTEXT_CHAR_LIMIT = 1800
_DIGEST_CHAR_LIMIT = 300

ROUTER_SYSTEM = (
    "You classify questions asked of a Class 3 medical device company's quality "
    "management system during a regulatory audit. Respond with a single JSON "
    'object and nothing else: {"pattern": <one of '
    + ", ".join(f'"{p}"' for p in PATTERNS)
    + '>, "doc_type": <one of "sop", "quality_manual", "capa", "ncr", "complaint", '
    '"mdr", "dfmea", "pfmea", "trace_matrix", "dhr", "verification_report" or null>}. '
    'Use "aggregate" for counts, totals, or listings across many records. Use '
    '"external" when the question needs public regulatory or scientific sources '
    "outside the company's own QMS (FDA MAUDE, recalls, 510(k)/PMA, eCFR or CFR "
    "text, FDA guidance, ClinicalTrials.gov, PubMed, the public web). Use "
    '"out_of_scope" for greetings or questions unrelated to the QMS. Set doc_type '
    "only when the question clearly targets one document family."
)

GRADER_SYSTEM = (
    "You judge whether retrieved quality-system excerpts can answer an auditor's "
    "question. Respond with a single JSON object and nothing else: "
    '{"sufficient": true|false, "reason": "<one short sentence>"}. '
    "Sufficient means the excerpts contain the specific facts needed, not merely "
    "the same topic."
)

REWRITER_SYSTEM = (
    "You rewrite a search query that failed to retrieve the right quality-system "
    "documents. Use precise QMS vocabulary (document identifiers, CAPA, NCR, MDR, "
    "revision, effective date). Respond with the rewritten query on a single line "
    "and nothing else."
)

GENERATOR_SYSTEM = (
    "You answer an auditor's question using ONLY the numbered sources provided. "
    "After every factual claim, append the marker of the source that supports it, "
    "like [1] or [2]. Never state a fact without a marker. Quote identifiers, "
    "revisions, and dates exactly as written in the sources. Sources beginning "
    "with 'EXTERNAL SOURCE (not QMS evidence)' are public reference data, not "
    "company records: attribute them explicitly (for example 'according to FDA "
    "MAUDE data') and keep them clearly separate from statements about the "
    "company's own QMS documents. If the sources do not contain the answer, "
    "reply with exactly INSUFFICIENT_EVIDENCE."
)

VERIFIER_SYSTEM = (
    "You verify that an answer is entailed by its cited sources. Respond with a "
    "single JSON object and nothing else: "
    '{"grounded": true|false, "unsupported_claims": ["<claim>", ...]}. '
    "An answer is grounded only if every factual claim is supported by the "
    "source it cites."
)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def source_excerpt(parent: dict[str, Any]) -> str:
    """The excerpt shown for one source: the parent section clipped to the
    context budget, but with the child passage that actually matched guaranteed
    to appear verbatim. A long parent clips to its head, which can drop the
    matched passage sitting in its tail — leaving the generator to answer from a
    section that no longer contains the sentence retrieval found. When that
    happens, lead with the matched child so the evidence is always present."""
    text = parent["text"]
    child = parent.get("matched_child_text")
    clipped = _clip(text, _CONTEXT_CHAR_LIMIT)
    if not child or child in clipped:
        return clipped
    if len(child) >= _CONTEXT_CHAR_LIMIT:
        return _clip(child, _CONTEXT_CHAR_LIMIT)
    remaining = _CONTEXT_CHAR_LIMIT - len(child) - 2
    return f"{child}\n\n{_clip(text, remaining)}" if remaining > 0 else child


def format_sources(parents: list[dict[str, Any]]) -> str:
    blocks = [
        f"[{i}] {parent['citation']}\n{source_excerpt(parent)}"
        for i, parent in enumerate(parents, start=1)
    ]
    return "\n\n".join(blocks)


def format_marked_sources(marked_parents: list[tuple[int, dict[str, Any]]]) -> str:
    """Like format_sources, but each source keeps the marker the answer used.
    Renumbering a cited subset 1..k would make the verifier read [3] in the
    answer as citing a different source than the generator meant."""
    blocks = [
        f"[{marker}] {parent['citation']}\n{source_excerpt(parent)}"
        for marker, parent in marked_parents
    ]
    return "\n\n".join(blocks)


def format_digests(parents: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {parent['citation']}: {_clip(parent['text'], _DIGEST_CHAR_LIMIT)}" for parent in parents
    )


def _history_prefix(history: list[dict[str, str]], limit: int = 6) -> str:
    if not history:
        return ""
    lines = [
        f"{turn['role']}: {_clip(turn['content'], _DIGEST_CHAR_LIMIT)}" for turn in history[-limit:]
    ]
    return "Conversation so far:\n" + "\n".join(lines) + "\n\n"


def router_messages(question: str) -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content=ROUTER_SYSTEM),
        ChatMessage(role="user", content=question),
    ]


def grader_messages(question: str, parents: list[dict[str, Any]]) -> list[ChatMessage]:
    body = f"Question: {question}\n\nExcerpts:\n{format_digests(parents)}"
    return [
        ChatMessage(role="system", content=GRADER_SYSTEM),
        ChatMessage(role="user", content=body),
    ]


def rewriter_messages(question: str, failed_query: str, reason: str) -> list[ChatMessage]:
    body = (
        f"Original question: {question}\n"
        f"Failed query: {failed_query}\n"
        f"Why retrieval was insufficient: {reason or 'nothing relevant returned'}"
    )
    return [
        ChatMessage(role="system", content=REWRITER_SYSTEM),
        ChatMessage(role="user", content=body),
    ]


def generator_messages(
    question: str, parents: list[dict[str, Any]], history: list[dict[str, str]]
) -> list[ChatMessage]:
    body = f"{_history_prefix(history)}Sources:\n{format_sources(parents)}\n\nQuestion: {question}"
    return [
        ChatMessage(role="system", content=GENERATOR_SYSTEM),
        ChatMessage(role="user", content=body),
    ]


def verifier_messages(
    answer: str, cited_parents: list[tuple[int, dict[str, Any]]]
) -> list[ChatMessage]:
    body = f"Answer:\n{answer}\n\nCited sources:\n{format_marked_sources(cited_parents)}"
    return [
        ChatMessage(role="system", content=VERIFIER_SYSTEM),
        ChatMessage(role="user", content=body),
    ]
