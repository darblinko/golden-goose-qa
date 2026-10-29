"""Deterministic identifier scheme for the Halvern Medical corpus.

Every ID is allocated from the world-build RNG so a seed fully determines the
corpus. Formats mirror common QMS numbering conventions.
"""

from datetime import date

# The corpus is generated "as of" this date; overdue/aging defects are stable
# relative to it.
WORLD_TODAY = date(2026, 7, 1)

# QMSR (21 CFR 820 incorporating ISO 13485:2016) effective date: documents whose
# latest revision predates this cite QSR sections, later ones cite ISO clauses.
QMSR_EFFECTIVE = date(2026, 2, 2)


def sop_id(n: int) -> str:
    return f"SOP-{n:03d}"


def wi_id(n: int) -> str:
    return f"WI-{n:03d}"


def req_id(n: int) -> str:
    return f"REQ-{n:03d}"


def design_output_id(n: int) -> str:
    return f"DO-{n:03d}"


def protocol_id(n: int) -> str:
    return f"VTP-{n:03d}"


def report_id(n: int) -> str:
    return f"VTR-{n:03d}"


def ncr_id(year: int, n: int) -> str:
    return f"NCR-{year}-{n:03d}"


def capa_id(year: int, n: int) -> str:
    return f"CAPA-{year}-{n:03d}"


def complaint_id(year: int, n: int) -> str:
    return f"C-{year}-{n:04d}"


def mdr_id(n: int) -> str:
    return f"MDR-{n:04d}"


def supplier_id(n: int) -> str:
    return f"SUP-{n:03d}"


def supplier_audit_id(year: int, n: int) -> str:
    return f"ASR-{year}-{n:02d}"


def internal_audit_id(year: int, n: int) -> str:
    return f"AUD-{year}-{n:02d}"


def management_review_id(year: int, n: int) -> str:
    return f"MRM-{year}-{n:02d}"


def lot_number(year: int, n: int) -> str:
    return f"L{year % 100}{n:04d}"
