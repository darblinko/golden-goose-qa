"""ID regex bank: find and normalize document/entity references in text.

One bank for every corpus identifier family, with separator normalization
(en/em dashes fold to hyphens). Matches are validated by callers against the
registry — an unknown id is a dangling reference worth surfacing, never an
edge.
"""

import re

# Document-key families that exist as files in the corpus, plus entity ids
# (REQ, DO, SUP) that live only inside matrices. Shared by the exact matcher and
# the OCR-correction matcher so both stay in sync.
_FAMILY = (
    "DFMEA|PFMEA|EMDR|CAPA|AUD|MRM|CIP|CER|CTL|NCR|MDR|VTR|VTP|SOP|PRS|RMP|RMR|"
    "TRN|ASL|ASR|REQ|SUP|QM|WI|DP|RA|TM|DO"
)

_ID_RE = re.compile(
    r"\b(?:"
    rf"(?:{_FAMILY})"
    r"-[0-9]{2,4}(?:-[0-9]{2,4})?"
    r"|C-[0-9]{4}-[0-9]{4}"
    r"|DHR-L[0-9]{2}[- ]?[0-9]{4}"
    r")\b"
)

_DASHES_RE = re.compile(r"[‐-―−]")  # noqa: RUF001 — the whole point is folding lookalike dashes

# Glyphs a scanner emits for digits. Folded only inside an id's numeric body,
# never its family prefix — SOP's own S/O must not become 5/0.
_OCR_FOLD = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "s": "5"})
_OCR_BODY = r"[0-9OoIlSs]"
# A loosely-matched family reference whose numeric body may carry OCR lookalikes.
# Case-insensitive so a misread lowercase prefix is still a correction candidate.
_LOOSE_FAMILY_RE = re.compile(
    rf"\b({_FAMILY})-({_OCR_BODY}{{2,4}}(?:-{_OCR_BODY}{{2,4}})?)\b",
    re.IGNORECASE,
)


def normalize_id(raw: str) -> str:
    return _DASHES_RE.sub("-", raw).strip().upper()


def find_ids(text: str) -> list[str]:
    """All identifier mentions in order, normalized, first occurrence kept."""
    seen: set[str] = set()
    found: list[str] = []
    for match in _ID_RE.finditer(_DASHES_RE.sub("-", text)):
        normalized = normalize_id(match.group(0))
        if normalized not in seen:
            seen.add(normalized)
            found.append(normalized)
    return found


def _leading_zero_variants(digits: str) -> list[str]:
    """The segment as-is plus zero-padded widths of its significant digits, so an
    OCR reference that dropped or gained a leading zero can still line up with the
    registry's canonical width."""
    stripped = digits.lstrip("0") or "0"
    variants = [digits]
    for width in (2, 3, 4):
        padded = stripped.zfill(width)
        if len(stripped) <= width and padded not in variants:
            variants.append(padded)
    return variants


def _correction_candidates(prefix: str, body: str) -> list[str]:
    """Normalized id candidates for a loose <prefix>-<body> OCR token: fold digit
    lookalikes in the body (every body glyph then being a digit), then expand
    leading-zero widths per numeric segment."""
    combos = [""]
    for segment in body.translate(_OCR_FOLD).split("-"):
        combos = [
            f"{combo}-{variant}" if combo else variant
            for combo in combos
            for variant in _leading_zero_variants(segment)
        ]
    return [f"{prefix.upper()}-{combo}" for combo in combos]


def find_ids_with_correction(text: str, known: frozenset[str] | set[str]) -> list[str]:
    """`find_ids` plus registry-validated OCR corrections. A reference whose
    digits were misread as letters (O->0, I->1, S->5) or whose leading zeros
    drifted is recovered only when its candidate forms resolve to exactly one
    known id; an ambiguous match (two known ids) or an unknown token is left out
    rather than guessed — a missed reference is recoverable, a wrong edge is not.
    Corrections are appended after the exact matches, deterministically."""
    normalized_text = _DASHES_RE.sub("-", text)
    found = find_ids(text)
    seen = set(found)
    for match in _LOOSE_FAMILY_RE.finditer(normalized_text):
        prefix, body = match.group(1, 2)
        if all(char.isdigit() or char == "-" for char in body):
            continue  # already exact-shaped; find_ids and the registry handle it
        matches = {c for c in _correction_candidates(prefix, body) if c in known}
        if len(matches) == 1:
            corrected = next(iter(matches))
            if corrected not in seen:
                seen.add(corrected)
                found.append(corrected)
    return found


def split_ids(cell: str) -> list[str]:
    """Ids from a delimited matrix cell ("DO-001, DO-002"); non-ids dropped."""
    parts = [normalize_id(part) for part in re.split(r"[,;]", cell) if part.strip()]
    return [part for part in parts if _ID_RE.fullmatch(part)]
