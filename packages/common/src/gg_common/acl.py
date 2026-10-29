"""Access control vocabulary shared by every tool path.

One choke point decides what "restricted" means: complaint and MDR records
carry patient-adjacent narratives, so the auditor_readonly role — an external
auditor at the kiosk — never receives their content through retrieval, SQL,
or graph traversal. QA staff and admins see everything. Decisions here are
fail-closed: an unknown role gets the least access, and content whose level
is unknown is treated as restricted.
"""

from collections.abc import Iterable, Mapping
from typing import Any

ROLES = ("admin", "qa_user", "auditor_readonly")

ACCESS_GENERAL = "general"
ACCESS_RESTRICTED = "restricted"
ACCESS_LEVELS = (ACCESS_GENERAL, ACCESS_RESTRICTED)

# Document families whose content is restricted. Complaint files, MDRs, and
# eMDR exports carry event narratives that stay inside the quality team;
# their existence (ids, links, counts in the graph) is not a secret — their
# text is.
RESTRICTED_DOC_TYPES = frozenset({"complaint", "mdr", "emdr"})

# The complete vocabulary of doc types whose content is known to be safe for
# every role. Anything not on this list — including a missing or misspelled
# doc_type — is treated as restricted; new document families must be
# classified here before their content reaches unprivileged callers.
KNOWN_GENERAL_DOC_TYPES = frozenset(
    {
        "quality_manual",
        "sop",
        "wi",
        "design_input",
        "design_plan",
        "risk_plan",
        "risk_analysis",
        "risk_report",
        "trace_matrix",
        "dfmea",
        "pfmea",
        "training_matrix",
        "supplier_list",
        "supplier_audit",
        "internal_audit",
        "management_review",
        "clinical_plan",
        "clinical_report",
        "control_plan",
        "capa",
        "ncr",
        "verification_report",
        "dhr",
        "dhr_scanned",
    }
)

# Record-key prefixes matching the restricted families, for tool paths that
# are addressed by document key rather than by type (graph anchors).
_RESTRICTED_KEY_PREFIXES = ("C-", "MDR-", "EMDR-")

# Synthetic citation doc_types produced by non-corpus tools — a SQL/graph tool
# result or an external web result — rather than an ingested document. They
# carry no corpus doc_type, so their level is judged from the record keys they
# were read from (counts and public sources are general; text pulled from a
# restricted record names that record's key and so fails closed).
_NON_DOCUMENT_DOC_TYPES = frozenset({"tool_result", "external_result"})


def access_level_for(doc_type: str | None) -> str:
    """Only explicitly known-general types are general; restricted, unknown,
    or missing types all fail closed to restricted."""
    return ACCESS_GENERAL if doc_type in KNOWN_GENERAL_DOC_TYPES else ACCESS_RESTRICTED


def can_read_restricted(role: str) -> bool:
    return role in ("admin", "qa_user")


def allowed_access_levels(role: str) -> tuple[str, ...]:
    """Levels a role may retrieve. Callers that receive the full tuple can
    skip filtering entirely; a proper subset must be enforced."""
    if can_read_restricted(role):
        return ACCESS_LEVELS
    return (ACCESS_GENERAL,)


def is_restricted_key(doc_key: str) -> bool:
    return doc_key.upper().startswith(_RESTRICTED_KEY_PREFIXES)


def citation_access_level(citation: Mapping[str, Any]) -> str:
    """The level a single stored citation demands. A restricted-family doc_type
    or a restricted record key — whether cited directly or listed in
    source_doc_keys behind a graph/tool answer — makes it restricted. Synthetic
    tool/external citations with no restricted source key are general (counts and
    public sources are not secret); every other corpus doc_type fails closed."""
    keys = [citation.get("doc_key"), *(citation.get("source_doc_keys") or [])]
    if any(isinstance(key, str) and is_restricted_key(key) for key in keys):
        return ACCESS_RESTRICTED
    doc_type = citation.get("doc_type")
    if doc_type in _NON_DOCUMENT_DOC_TYPES:
        return ACCESS_GENERAL
    return access_level_for(doc_type)


def message_access_level(citations: Iterable[Mapping[str, Any]]) -> str:
    """The most restrictive level any of a message's citations demands. A
    message with no restricted citation (including one with no citations at all,
    like a user turn or an out-of-scope reply) is general. Persisted per message
    so replay can be re-authorized against the reader's current role."""
    for citation in citations:
        if citation_access_level(citation) == ACCESS_RESTRICTED:
            return ACCESS_RESTRICTED
    return ACCESS_GENERAL


def role_can_read_access_level(role: str, access_level: str) -> bool:
    """Whether a role may see content stored at this level. Used to re-check a
    persisted message on replay after a possible role downgrade."""
    return access_level in allowed_access_levels(role)
