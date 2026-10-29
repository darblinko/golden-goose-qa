"""Prompt-injection sanitization applied to all extracted text at ingestion.

Controlled QMS documents should never contain instruction-like text aimed at
an LLM; when a pattern matches we neutralize it in place and record the hit in
the document's metrics so a poisoned source is visible, not silently trusted.
"""

import re
from dataclasses import dataclass

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+instructions", re.I),
    re.compile(r"disregard\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+instructions", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a|an)\s+", re.I),
    re.compile(r"<\s*/?\s*system\s*>", re.I),
    re.compile(r"\bsystem\s+prompt\b", re.I),
    re.compile(r"\bbegin\s+new\s+instructions\b", re.I),
    re.compile(r"\[/?INST\]"),
)

_REPLACEMENT = "[redacted-instruction-like-text]"


@dataclass(frozen=True)
class SanitizeResult:
    text: str
    hits: tuple[str, ...]


def sanitize_text(text: str) -> SanitizeResult:
    hits: list[str] = []
    cleaned = text
    for pattern in _INJECTION_PATTERNS:
        matches = pattern.findall(cleaned)
        if matches:
            hits.extend(m if isinstance(m, str) else pattern.pattern for m in matches)
            cleaned = pattern.sub(_REPLACEMENT, cleaned)
    return SanitizeResult(text=cleaned, hits=tuple(hits))
