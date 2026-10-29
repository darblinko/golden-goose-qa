"""Advisory LLM note over a deterministic audit report.

The gates themselves never involve a model; the note is commentary layered
on top. Any unusable model reply — wrong shape, not JSON, transport error —
falls back to the report's deterministic summary, so keyless deployments
degrade to a plain but always-correct sentence.
"""

import json

from gg_common.providers.base import ChatMessage, LLMProvider

from gg_retrieval.audit.report import AuditReport

ADVISORY_SYSTEM = (
    "You are advising a medical device quality team preparing for a "
    "regulatory audit. Given deterministic readiness-check results, respond "
    'with a single JSON object and nothing else: {"note": "<two to four '
    'sentences: which findings an auditor would pursue first and why>"}. '
    "Base the note only on the results provided; never invent findings."
)


def _report_digest(report: AuditReport) -> str:
    lines = []
    for result in report.results:
        line = f"- {result.check.title} [{result.check.kind}]: {result.status}"
        if result.status == "finding":
            line += f" ({len(result.rows)} rows)"
        if result.status == "error":
            line += f" ({result.detail})"
        lines.append(line)
    return "\n".join(lines)


async def advisory_note(llm: LLMProvider, report: AuditReport) -> str:
    messages = [
        ChatMessage(role="system", content=ADVISORY_SYSTEM),
        ChatMessage(role="user", content=f"Readiness check results:\n{_report_digest(report)}"),
    ]
    try:
        raw = await llm.complete(messages)
        parsed = json.loads(raw)
        note = parsed.get("note") if isinstance(parsed, dict) else None
    except Exception:
        return report.summary
    if not isinstance(note, str) or not note.strip():
        return report.summary
    return note.strip()
