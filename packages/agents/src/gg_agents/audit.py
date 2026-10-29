"""Audit payload for a completed chat turn. Records what the architecture
requires per response: model, prompt hash, retrieved chunk ids, route, and
verification outcome. Written to audit.audit_log by the API layer."""

from typing import Any

from gg_common.audit import AuditEvent
from gg_common.settings import AppSettings

from gg_agents.state import AgentState

TURN_ACTION = "chat.turn"
TURN_FAILURE_ACTION = "chat.turn.failed"


def build_turn_audit_event(
    state: AgentState, *, settings: AppSettings, thread_id: str, actor: str
) -> AuditEvent:
    payload: dict[str, Any] = {
        "thread_id": thread_id,
        "question": state.get("question", ""),
        "pattern": state.get("pattern", ""),
        "doc_type_filter": state.get("doc_type"),
        "as_of_filter": state.get("as_of"),
        "final_query": state.get("query", ""),
        "rewrites": state.get("rewrites", 0),
        "model": settings.providers.llm_model,
        "prompt_hash": state.get("prompt_hash", ""),
        "chunk_ids": [c["chunk_id"] for c in state.get("chunks", [])],
        "cited": [c["citation"] for c in state.get("citations", [])],
        "verdict": state.get("verdict", ""),
        "verifier_error": state.get("verifier_error"),
        "external_error": state.get("external_error"),
    }
    return AuditEvent(actor=actor, action=TURN_ACTION, payload=payload)


def build_turn_failure_audit_event(
    question: str, *, thread_id: str, actor: str, error: str
) -> AuditEvent:
    """A turn that died mid-flight still leaves an audit row. The error text
    is the exception type and message, not a traceback."""
    payload: dict[str, Any] = {
        "thread_id": thread_id,
        "question": question,
        "error": error[:500],
    }
    return AuditEvent(actor=actor, action=TURN_FAILURE_ACTION, payload=payload)
