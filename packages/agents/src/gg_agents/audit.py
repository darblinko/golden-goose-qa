"""Audit payload for a completed chat turn. Records what the architecture
requires per response: model, prompt hash, retrieved chunk ids, route,
verification outcome, the answer text with its SHA-256 digest, the citations
shown with it, and a digest of every evidence block the generator was given.
Written to audit.audit_log by the API layer; the audit chain keeps the answer
record after the thread and its messages are deleted."""

import hashlib
from typing import Any

from gg_common.audit import AuditEvent
from gg_common.settings import AppSettings

from gg_agents.state import AgentState

TURN_ACTION = "chat.turn"
TURN_STARTED_ACTION = "chat.turn.started"
TURN_FAILURE_ACTION = "chat.turn.failed"

_CITATION_FIELDS = (
    "marker",
    "doc_key",
    "doc_type",
    "revision",
    "version_id",
    "section_path",
    "page",
    "provenance",
    "source_doc_keys",
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _evidence_record(parent: dict[str, Any]) -> dict[str, Any]:
    """Identity and digest of one evidence block: for a tool result the
    section_path is the executed query, for a document the section."""
    return {
        "parent_id": parent.get("parent_id"),
        "doc_key": parent.get("doc_key"),
        "doc_type": parent.get("doc_type"),
        "version_id": parent.get("version_id"),
        "section_path": parent.get("section_path"),
        "provenance": parent.get("provenance", "internal"),
        "text_sha256": _sha256(parent.get("text", "")),
    }


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
        "citations": [
            {field: c.get(field) for field in _CITATION_FIELDS} for c in state.get("citations", [])
        ],
        "evidence": [
            _evidence_record(p)
            for p in [*state.get("parents", []), *state.get("external_parents", [])]
        ],
        "answer": state.get("answer", ""),
        "answer_sha256": _sha256(state.get("answer", "")),
        "verdict": state.get("verdict", ""),
        "verifier_error": state.get("verifier_error"),
        "external_error": state.get("external_error"),
    }
    return AuditEvent(actor=actor, action=TURN_ACTION, payload=payload)


def build_turn_started_audit_event(question: str, *, thread_id: str, actor: str) -> AuditEvent:
    """Written with the user message, before the agent runs, so a turn that
    never completes (a killed process, a lost connection) is still on record."""
    payload: dict[str, Any] = {"thread_id": thread_id, "question": question}
    return AuditEvent(actor=actor, action=TURN_STARTED_ACTION, payload=payload)


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
