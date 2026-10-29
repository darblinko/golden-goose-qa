"""Query-time QSR <-> ISO 13485 vocabulary crosswalk.

An auditor asks in whichever regulatory dialect they work in; the corpus is
written in QSR-era vocabulary with dual citations. Matched phrases and clause
numbers append their counterpart vocabulary to the copy of the query used for
*sparse* retrieval only; the dense embedding and the reranker both see the
original query untouched, so expansion can add keyword recall without shifting
semantics or biasing the cross-encoder toward the appended terms.

The crosswalk is curated, not learned: every entry maps audit phrasing to the
terminology the quality system's own procedures use. Phrases match on whole-word
boundaries (a simple trailing plural tolerated) so a phrase never fires from
inside a larger word, and the number of appended sources is capped so a
clause-heavy query cannot balloon the sparse query and dilute precision.
"""

import re

# A clause-heavy or dialect-dense query can match many entries; cap how many
# append so the sparse query stays a focused recall aid rather than a keyword
# dump. Phrase matches (crosswalk order) are considered before clause matches
# (query order), and the first this-many distinct additions are kept.
_MAX_EXPANSIONS = 6

# ISO 13485 phrasing -> QSR-era terminology used in the corpus.
_TERM_CROSSWALK: tuple[tuple[str, str], ...] = (
    ("advisory notice", "field action recall correction removal"),
    ("vigilance", "medical device reporting MDR adverse event"),
    ("top management", "management with executive responsibility management review"),
    ("management representative", "management with executive responsibility"),
    ("work environment", "environmental control contamination control"),
    ("nonconforming output", "nonconforming product"),
    ("nonconformity", "nonconformance nonconforming product NCR"),
    ("monitoring and measuring equipment", "calibration inspection measuring test equipment"),
    ("measuring equipment", "calibration"),
    # ISO 4.2.3 "medical device file" is the device specification set — the QSR
    # Device Master Record (820.181). It is NOT the Design History File
    # (820.30(j)), which records the design process; conflating the two would
    # surface design records for a device-specification query.
    ("medical device file", "device master record"),
    ("design and development", "design control"),
    ("purchasing process", "supplier evaluation purchasing controls"),
    ("customer feedback", "complaint handling"),
    ("feedback process", "complaint handling"),
    ("corrective action", "CAPA corrective and preventive action"),
    ("preventive action", "CAPA corrective and preventive action"),
    ("competence", "training and competency"),
    ("infrastructure", "facilities equipment maintenance"),
    # QSR phrasing -> ISO terminology, for the reverse direction.
    ("device master record", "medical device file"),
    ("complaint file", "complaint handling customer feedback"),
)

# Clause / section numbers -> the procedure topic they govern. Citing either
# regime's number should surface the corpus procedure for that topic.
_CLAUSE_TOPICS: dict[str, str] = {
    # ISO 13485:2016 clauses
    "4.2.4": "document and record control",
    "4.2.5": "records retention",
    "5.6": "management review",
    "6.2": "training and competency",
    "6.4": "work environment environmental contamination control",
    "7.3": "design control",
    "7.4": "supplier evaluation purchasing controls",
    "7.5.1": "production and process control",
    "7.5.7": "sterilization process control",
    "7.5.8": "identification unique device identification device history record",
    "7.5.11": "packaging and shipping",
    "7.6": "calibration monitoring and measuring equipment",
    "8.1": "statistical techniques sampling",
    "8.2.2": "complaint handling",
    "8.2.3": "medical device reporting",
    "8.2.4": "internal audit",
    "8.3": "control of nonconforming product",
    "8.3.3": "field action recall advisory notice",
    "8.5.2": "corrective and preventive action CAPA",
    "8.5.3": "corrective and preventive action CAPA",
    # 21 CFR sections
    "820.20": "management review executive responsibility",
    "820.22": "internal audit",
    "820.25": "training and competency",
    "820.30": "design control",
    "820.40": "document and record control",
    "820.50": "supplier evaluation purchasing controls",
    "820.70": "production and process control",
    "820.72": "calibration inspection measuring test equipment",
    "820.75": "process validation sterilization",
    "820.80": "incoming inspection acceptance activities",
    "820.90": "control of nonconforming product",
    "820.100": "corrective and preventive action CAPA",
    "820.120": "labeling control",
    "820.130": "packaging and shipping",
    "820.180": "records retention",
    "820.181": "device master record",
    "820.184": "device history record",
    "820.198": "complaint handling",
    "820.250": "statistical techniques sampling",
    "803": "medical device reporting adverse event",
    "806": "field action recall correction removal",
    "830": "unique device identification UDI",
}

_CLAUSE_RE = re.compile(r"\b(8\d\d(?:\.\d+)?|\d(?:\.\d+){1,2})\b")

# Each crosswalk phrase as a whole-word pattern: a word boundary at both ends so
# it never matches inside a larger token, plus an optional simple English plural
# ("s"/"es") on the trailing word so "advisory notices" still matches "advisory
# notice". Irregular plurals (y -> ies) are intentionally not handled — the goal
# is to stop false substring hits, not to build a stemmer.
_PHRASE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{re.escape(phrase)}(?:e?s)?\b"), terms) for phrase, terms in _TERM_CROSSWALK
)


def expand_query(query: str) -> str:
    """Return the query with crosswalk vocabulary appended, or unchanged when
    nothing matches. Phrases match on whole-word boundaries; additions are
    capped, deduplicated, and order-stable so expansion is deterministic."""
    lowered = query.lower()
    additions: list[str] = [terms for pattern, terms in _PHRASE_PATTERNS if pattern.search(lowered)]
    for match in _CLAUSE_RE.finditer(lowered):
        topic = _CLAUSE_TOPICS.get(match.group(1))
        if topic:
            additions.append(topic)
    if not additions:
        return query
    # Dedupe identical additions before the cap so two clauses mapping to the
    # same topic don't spend two of the capped slots, then keep the first few.
    capped = list(dict.fromkeys(additions))[:_MAX_EXPANSIONS]
    unique_terms = list(dict.fromkeys(" ".join(capped).split()))
    return f"{query}\n{' '.join(unique_terms)}"
