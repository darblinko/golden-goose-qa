"""Deterministic question-to-tool mapping.

Routing overrides and tool plans are computed with regexes, not the LLM, for
two reasons: high-precision patterns (record ids, REQ ids, count phrasing)
should never depend on model behavior during an audit, and keyless (fake
provider) deployments must still reach the warehouse and graph tools.
The LLM router remains the fallback for everything these patterns miss.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime

_REQ_ID_RE = re.compile(r"\bREQ-\d+\b")
# Document keys are one or more uppercase segments ending in a 3-digit number:
# SOP-013, QM-001, and compound keys like WI-MFG-014. Matching the whole key
# (not just its MFG-014 tail) is what lets an as-of question about WI-MFG-014
# resolve the real document instead of a phantom substring.
_DOC_KEY_RE = re.compile(r"\b[A-Z]{2,6}(?:-[A-Z]{2,6})*-\d{3}\b")
_RECORD_ID_RE = re.compile(r"\b(?:CAPA|NCR|MDR)-\d{4}(?:-\d+)?\b|\bC-\d{4}-\d{3,}\b")
# Thread-walk intent: a record id paired with any of these asks for the graph
# thread around the record (source, escalation, filing), not vector retrieval
# of the single record's text.
_THREAD_WALK_RE = re.compile(
    r"\bwalk (?:me )?through\b|\bthread\b|\bend[- ]to[- ]end\b|\btrace\b"
    r"|\bchain\b|\btraverse\b|\bfull (?:history|record|dossier)\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_TRAINING_RE = re.compile(r"\btrain(?:ed|ing)?\b", re.IGNORECASE)
_AGGREGATE_RE = re.compile(
    r"\b(?:how many|count|total number|list (?:all|the|every)"
    r"|(?:are|were|do|does|have|has) (?:any|all))\b",
    re.IGNORECASE,
)
_UNVERIFIED_RE = re.compile(
    r"\brequirements?\b.*\bverif|\bverif\w*\b.*\brequirements?\b", re.IGNORECASE | re.DOTALL
)
_COUNT_PHRASE_RE = re.compile(r"\bhow many\b|\bcount\b|\btotal number\b", re.IGNORECASE)
_EXTERNAL_SOURCE_RE = re.compile(
    r"\bmaude\b|\bopenfda\b|\becfr\b|\b\d+\s+cfr\b|\bfda guidance\b|\bguidance document"
    r"|\bfda recall|\brecall database\b|\bwarning letter|\bclinicaltrials\b"
    r"|\bclinical trials?\b|\bpubmed\b|\bpublished literature\b|\bgudid\b"
    r"|\b510\(k\)|\b510k\b|\bpremarket approval\b|\bweb search\b|\bsearch the web\b",
    re.IGNORECASE,
)
_CFR_CITE_RE = re.compile(r"\b\d+\s+CFR\s+[0-9.]+\b", re.IGNORECASE)
# A rate-comparison question pits an internal figure against a public source as
# a *rate* — it needs a comparison verb and an explicit rate/normalization word,
# on top of naming an external source. "Compare our complaints to MAUDE" (a raw
# count comparison) deliberately does not match; only "complaint rate ... compare
# to MAUDE" does, so the plain external path is unaffected.
_COMPARE_VERB_RE = re.compile(
    r"\bcompare[ds]?\b|\bcomparison\b|\bversus\b|\bvs\.?\b|\brelative to\b|\bbenchmark(?:ed|s)?\b",
    re.IGNORECASE,
)
_RATE_RE = re.compile(
    r"\brates?\b|\bfrequency\b|\bincidence\b|\bproportion\b|\bpercentage\b"
    r"|\bnormali[sz]ed?\b|\bper\s+(?:\d|thousand|million|unit|device|patient|capita)",
    re.IGNORECASE,
)

# (matcher, view, date column, plural label, has status/age columns) for
# deterministic count SQL. `has_status` marks views that expose is_open and
# age_days — the MDR register does not, so status/age qualifiers cannot be
# honored there and the count refuses rather than answer a bare total.
_COUNT_TARGETS: tuple[tuple[re.Pattern[str], str, str, str, bool], ...] = (
    (
        re.compile(r"\bcomplaints?\b", re.IGNORECASE),
        "registers.v_complaint_register",
        "received",
        "complaints",
        True,
    ),
    (
        re.compile(r"\bncrs?\b|\bnonconformance\b|\bnonconforming\b", re.IGNORECASE),
        "registers.v_ncr_register",
        "opened",
        "NCRs",
        True,
    ),
    (
        re.compile(r"\bcapas?\b|\bcorrective action", re.IGNORECASE),
        "registers.v_capa_register",
        "opened",
        "CAPAs",
        True,
    ),
    (
        re.compile(r"\bmdrs?\b|\bmedical device report", re.IGNORECASE),
        "registers.v_mdr_register",
        "submitted",
        "MDRs",
        False,
    ),
)

# Status and age qualifiers a count must honor rather than silently drop.
_OPEN_RE = re.compile(r"\b(?:still\s+)?open\b|\bunclosed\b|\boutstanding\b", re.IGNORECASE)
_CLOSED_RE = re.compile(r"\bclosed\b|\bresolved\b", re.IGNORECASE)
_AGE_DAYS_RE = re.compile(
    r"\b(?:older than|more than|greater than|over|past|exceeding|>)\s*(\d{1,4})\s*days?\b",
    re.IGNORECASE,
)


def route_override(question: str) -> str | None:
    """Return a pattern name when the question is unambiguous, else None.

    Checked before the LLM router; order matters (a question naming REQ-017
    is a trace walk even when it also says "which requirements lack...")."""
    if _REQ_ID_RE.search(question):
        return "trace"
    if _UNVERIFIED_RE.search(question):
        return "trace"
    if _TRAINING_RE.search(question) and _DOC_KEY_RE.search(question):
        return "trace"
    if _RECORD_ID_RE.search(question) and _THREAD_WALK_RE.search(question):
        # "Walk me through CAPA-2025-014 end to end" is a graph thread walk, not
        # vector retrieval of the single record — route it to graph_walk.
        return "trace"
    if is_rate_comparison(question):
        # "How does our complaint rate compare to MAUDE?" needs an internal and
        # an external numerator plus a shared denominator, not vector retrieval.
        # Checked before the plain external route so a rate question is not
        # answered as a one-sided lookup.
        return "compare"
    if _EXTERNAL_SOURCE_RE.search(question):
        # Naming a public source (MAUDE, eCFR, PubMed...) routes external even
        # for count phrasing — the external node still runs internal retrieval,
        # so mixed comparison questions get both evidence kinds.
        return "external"
    if _AGGREGATE_RE.search(question):
        return "aggregate"
    if re.search(r"\bwhich suppliers?\b", question, re.IGNORECASE):
        return "aggregate"
    if _RECORD_ID_RE.search(question):
        return "record"
    return None


def is_rate_comparison(question: str) -> bool:
    """True when the question asks to compare an internal *rate* against a public
    source. Requires all three of: an external source name, a comparison verb,
    and an explicit rate/normalization word — so a raw-count comparison stays on
    the plain external path and only genuine rate questions reach the compare
    route, where both a numerator and a shared denominator are demanded."""
    return bool(
        _EXTERNAL_SOURCE_RE.search(question)
        and _COMPARE_VERB_RE.search(question)
        and _RATE_RE.search(question)
    )


_AS_OF_RE = re.compile(
    r"\b(?:as of|in effect on|effective on)\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}-[A-Za-z]{3}-\d{4}"
    r"|[A-Za-z]+\s+\d{1,2},?\s+\d{4}"
    r"|[A-Za-z]+\s+\d{4})",
    re.IGNORECASE,
)
_AS_OF_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%B %d %Y", "%b %d %Y", "%B %Y", "%b %Y")


@dataclass(frozen=True)
class RetrievalScope:
    """Hard document/revision scope for retrieval, extracted deterministically.

    A single named document key becomes a doc_key filter; a "Rev A"/"Revision B"
    token alongside it becomes an exact revision filter. Both empty means the
    question named no single document and retrieval stays broad."""

    doc_key: str | None = None
    revision: str | None = None


# A cited revision token: "Rev A", "Revision B", "rev. C", "Rev A2", "Rev 3".
# The token itself must be uppercase letters and/or digits — how a revision is
# written on a controlled document — which also stops "revision history" and
# "current revision of ..." from being read as a revision identifier.
_REVISION_RE = re.compile(r"\b[Rr]ev(?:ision)?\.?\s+([A-Z]{1,2}\d{0,3}|\d{1,3})\b")


def _unique_doc_keys(question: str) -> list[str]:
    seen: list[str] = []
    for key in _DOC_KEY_RE.findall(question):
        if key not in seen:
            seen.append(key)
    return seen


def extract_scope(question: str) -> RetrievalScope:
    """Deterministic document + exact-revision scope for retrieval.

    Exactly one distinct document key in the question is a hard doc_key filter;
    an accompanying revision token becomes an exact revision filter. Two or more
    distinct keys are ambiguous (a comparison, not one-document scope) and yield
    no scope. A revision with no single doc key is dropped — a bare revision
    cannot be pinned to a document. This turns the lexical hints the question
    only implies into the enforced non-leakage boundary retrieval applies to
    both channels, preserved across query rewrites via agent state."""
    keys = _unique_doc_keys(question)
    if len(keys) != 1:
        return RetrievalScope()
    match = _REVISION_RE.search(question)
    return RetrievalScope(doc_key=keys[0], revision=match.group(1) if match else None)


def extract_as_of(question: str) -> date | None:
    """Deterministic as-of date detection ("as of 15-Mar-2024", "in effect on
    March 2024"). A month without a day means the first of that month. Text
    that resembles a date but parses as none (e.g. "as of fiscal 2024")
    yields None — retrieval then answers from current state, never a guess."""
    match = _AS_OF_RE.search(question)
    if match is None:
        return None
    raw = match.group("date").replace(",", "")
    for fmt in _AS_OF_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class WarehousePlan:
    """Either a saved query (name + params) or deterministic ad-hoc SQL."""

    saved: str | None = None
    params: dict[str, str] | None = None
    sql: str | None = None
    title: str | None = None


def warehouse_plan(question: str) -> WarehousePlan:
    count_plan = _count_plan(question)
    if count_plan is not None:
        return count_plan

    lowered = question.lower()
    if "overdue" in lowered and "effectiveness" in lowered:
        return WarehousePlan(saved="overdue_capa_effectiveness")
    if "open" in lowered and "capa" in lowered:
        return WarehousePlan(saved="open_capas")
    if "open" in lowered and ("ncr" in lowered or "nonconform" in lowered):
        return WarehousePlan(saved="open_ncrs")
    if "complaint" in lowered and "risk" in lowered:
        return WarehousePlan(saved="complaints_without_risk_evaluation")
    if ("action priority" in lowered or re.search(r"\bap\b", lowered)) and (
        "mismatch" in lowered or "disagree" in lowered or "incorrect" in lowered
    ):
        return WarehousePlan(saved="fmea_ap_mismatches")
    if "supplier" in lowered:
        return WarehousePlan(saved="supplier_audit_aging")
    if "training" in lowered:
        doc_key = _DOC_KEY_RE.search(question)
        if doc_key:
            return WarehousePlan(saved="training_for_document", params={"doc_key": doc_key.group()})
    if "requirement" in lowered and "verif" in lowered:
        return WarehousePlan(saved="unverified_requirements")
    if "mdr" in lowered or "medical device report" in lowered:
        return WarehousePlan(saved="mdr_register")
    return WarehousePlan(saved="register_counts")


def _count_plan(question: str) -> WarehousePlan | None:
    if not _COUNT_PHRASE_RE.search(question):
        return None
    for matcher, view, date_column, label, has_status in _COUNT_TARGETS:
        if not matcher.search(question):
            continue
        return _count_plan_for(question, view, date_column, label, has_status)
    return None


# The empty plan: a count whose qualifiers cannot be expressed against the
# target view. warehouse_plan returns it directly so the turn refuses with
# insufficient_evidence instead of answering an unqualified total.
_COUNT_REFUSAL = WarehousePlan()


def _count_plan_for(
    question: str, view: str, date_column: str, label: str, has_status: bool
) -> WarehousePlan:
    conditions: list[str] = []
    status_prefix = ""
    suffix_qualifiers: list[str] = []

    wants_open = bool(_OPEN_RE.search(question))
    wants_closed = bool(_CLOSED_RE.search(question))
    age_match = _AGE_DAYS_RE.search(question)

    if (wants_open or wants_closed or age_match) and not has_status:
        # e.g. "how many MDRs are still open" — the MDR register has no open or
        # age column, so any total we returned would silently ignore the
        # qualifier. Refuse instead of answering the wrong question.
        return _COUNT_REFUSAL
    if wants_open and wants_closed:
        return _COUNT_REFUSAL  # contradictory; refuse rather than pick one

    if wants_open:
        conditions.append("is_open")
        status_prefix = "open "
    elif wants_closed:
        conditions.append("NOT is_open")
        status_prefix = "closed "

    year_match = _YEAR_RE.search(question)
    if year_match:
        # int() guarantees the interpolated values are digits; the guard
        # re-validates the whole statement before execution.
        year = int(year_match.group(1))
        conditions.append(f"{date_column} >= '{year}-01-01' AND {date_column} < '{year + 1}-01-01'")
        suffix_qualifiers.append(f"in {year}")

    if age_match:
        days = int(age_match.group(1))
        conditions.append(f"age_days > {days}")
        suffix_qualifiers.append(f"older than {days} days")

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT count(*) AS total FROM {view}{where}"
    suffix = f" {' '.join(suffix_qualifiers)}" if suffix_qualifiers else ""
    return WarehousePlan(sql=sql, title=f"Count of {status_prefix}{label}{suffix}")


@dataclass(frozen=True)
class ExternalPlan:
    method: str  # maude | recalls | 510k | pma | gudid | compliance |
    #               ecfr | guidance | clinicaltrials | pubmed | web
    term: str


# Filler stripped when distilling an external search term from the question.
# Source names go too: "MAUDE reports about infusion pumps" should search MAUDE
# for "infusion pumps", not for the word "MAUDE".
_EXTERNAL_FILLER = frozenset(
    [
        "a",
        "an",
        "and",
        "about",
        "affecting",
        "against",
        "any",
        "are",
        "as",
        "been",
        "between",
        "by",
        "compare",
        "compared",
        "comparing",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "issued",
        "it",
        "its",
        "list",
        "many",
        "me",
        "most",
        "of",
        "on",
        "our",
        "over",
        "recent",
        "regarding",
        "require",
        "required",
        "requires",
        "search",
        "show",
        "tell",
        "that",
        "the",
        "their",
        "there",
        "these",
        "this",
        "to",
        "us",
        "was",
        "were",
        "what",
        "which",
        "who",
        "whose",
        "with",
        "adverse",
        "database",
        "do",
        "event",
        "events",
        "fda",
        "maude",
        "openfda",
        "pubmed",
        "literature",
        "published",
        "recall",
        "recalls",
        "recalled",
        "guidance",
        "document",
        "documents",
        "clinicaltrials",
        "clinical",
        "trial",
        "trials",
        "warning",
        "letter",
        "letters",
        "cfr",
        "ecfr",
        "regulation",
        "regulations",
        "report",
        "reports",
        "reported",
        "complaint",
        "complaints",
        "trend",
        "trends",
        "gudid",
        "udi",
        "web",
        "premarket",
        "approval",
        "approvals",
        "clearance",
        "clearances",
        "say",
        "says",
        "state",
        "states",
    ]
)


# Straight or curly quotes (u2018/u2019 single, u201c/u201d double)
# wrapping an explicit search term.
_QUOTED_RE = re.compile("[\"\u201c\u2018']([^\"\u201c\u201d\u2018\u2019']{3,})[\"\u201d\u2019']")


def _external_term(question: str) -> str:
    quoted = _QUOTED_RE.search(question)
    if quoted:
        return quoted.group(1).strip()
    words = re.findall(r"[A-Za-z0-9()./-]+", question)
    kept = [w for w in words if w.lower() not in _EXTERNAL_FILLER]
    return " ".join(kept) or question.strip()


def external_plan(question: str) -> ExternalPlan:
    """Map a question to one external tool family plus a distilled search term.

    Deterministic for the same reason as route_override: external lookups must
    work identically in keyless deployments and during an audit."""
    lowered = question.lower()
    term = _external_term(question)
    if "maude" in lowered or "adverse event" in lowered:
        return ExternalPlan("maude", term)
    if "recall" in lowered:
        return ExternalPlan("recalls", term)
    if "510" in lowered:
        return ExternalPlan("510k", term)
    if "pma" in lowered or "premarket approval" in lowered:
        return ExternalPlan("pma", term)
    if "gudid" in lowered or "udi" in lowered:
        return ExternalPlan("gudid", term)
    if "warning letter" in lowered or "compliance action" in lowered:
        return ExternalPlan("compliance", term)
    if "guidance" in lowered:
        return ExternalPlan("guidance", term)
    cfr_cite = _CFR_CITE_RE.search(question)
    if cfr_cite:
        return ExternalPlan("ecfr", cfr_cite.group())
    if "ecfr" in lowered or "cfr" in lowered or "regulation" in lowered:
        return ExternalPlan("ecfr", term)
    if "clinical trial" in lowered or "clinicaltrials" in lowered:
        return ExternalPlan("clinicaltrials", term)
    if "pubmed" in lowered or "literature" in lowered:
        return ExternalPlan("pubmed", term)
    return ExternalPlan("web", question.strip())


@dataclass(frozen=True)
class GraphPlan:
    method: str
    argument: str | None = None


def graph_plan(question: str) -> GraphPlan:
    req_id = _REQ_ID_RE.search(question)
    if req_id:
        return GraphPlan(method="requirement_trace", argument=req_id.group())
    doc_key = _DOC_KEY_RE.search(question)
    if _TRAINING_RE.search(question) and doc_key:
        return GraphPlan(method="training_status", argument=doc_key.group())
    record_id = _RECORD_ID_RE.search(question)
    if record_id:
        # The full record id (e.g. CAPA-2025-014, C-2025-0142) anchors the
        # thread walk; the record-id regex captures the whole id, not the
        # 3-digit tail a document-key regex would stop at.
        return GraphPlan(method="record_thread", argument=record_id.group())
    if _UNVERIFIED_RE.search(question):
        return GraphPlan(method="unverified_requirements")
    if doc_key:
        return GraphPlan(method="document_profile", argument=doc_key.group())
    return GraphPlan(method="unverified_requirements")
