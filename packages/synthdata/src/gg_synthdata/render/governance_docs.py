"""Word (.docx) renderers for governance records: internal audit reports and
management review minutes.

Both are uncontrolled records (no revision block), rendered in the same
label/value form idiom as CAPA records so the docx parser and the record
extractors treat them uniformly.
"""

from pathlib import Path

from docx.document import Document as DocumentType

from gg_synthdata.model import InternalAudit, ManagementReview, World
from gg_synthdata.render.common import fmt_date
from gg_synthdata.render.word_docs import _new_document, _save


def _form_table(document: DocumentType, rows: tuple[tuple[str, str], ...]) -> None:
    table = document.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    for i, (label, value) in enumerate(rows):
        table.rows[i].cells[0].text = label
        table.rows[i].cells[1].text = value


def render_internal_audit(world: World, audit: InternalAudit, out_dir: Path) -> Path:
    document = _new_document()
    document.add_heading(world.company, level=0)
    document.add_heading(f"Internal Audit Report — {audit.audit_id}", level=1)
    _form_table(
        document,
        (
            ("Report Number", audit.audit_id),
            ("Audit Date", fmt_date(audit.audit_date)),
            ("Lead Auditor", audit.lead_auditor),
            ("Process Areas Audited", "; ".join(audit.areas)),
            ("Documents in Scope", ", ".join(audit.scope_docs)),
            ("Result", audit.result),
            ("CAPAs Raised", ", ".join(audit.capa_ids) if audit.capa_ids else "None"),
        ),
    )
    document.add_paragraph("")
    document.add_heading("Findings", level=2)
    for i, finding in enumerate(audit.findings, start=1):
        document.add_paragraph(f"{i}. {finding}")
    document.add_paragraph("")
    document.add_paragraph(
        "Audit conducted per SOP-014, Internal Audit. Nonconforming findings are "
        "escalated to corrective action per SOP-004."
    )
    return _save(document, out_dir / f"{audit.audit_id}.docx")


def render_management_review(world: World, review: ManagementReview, out_dir: Path) -> Path:
    document = _new_document()
    document.add_heading(world.company, level=0)
    document.add_heading(f"Management Review Minutes — {review.review_id}", level=1)
    period = f"{fmt_date(review.period_start)} through {fmt_date(review.period_end)}"
    _form_table(
        document,
        (
            ("Review Number", review.review_id),
            ("Meeting Date", fmt_date(review.meeting_date)),
            ("Review Period", period),
            ("Chair", review.chair),
            ("Attendees", "; ".join(review.attendees)),
            ("CAPAs Opened", str(review.capas_opened)),
            ("CAPAs Closed", str(review.capas_closed)),
            ("NCRs Opened", str(review.ncrs_opened)),
            ("Complaints Received", str(review.complaints_received)),
            ("MDRs Submitted", str(review.mdrs_submitted)),
            (
                "Internal Audits Conducted",
                ", ".join(review.audit_ids) if review.audit_ids else "None",
            ),
        ),
    )
    document.add_paragraph("")
    document.add_heading("Decisions and Actions", level=2)
    for decision in review.decisions:
        document.add_paragraph(decision, style="List Bullet")
    document.add_paragraph("")
    document.add_paragraph(
        "Review conducted per SOP-015, Management Review, covering the quality "
        "system inputs required by that procedure."
    )
    return _save(document, out_dir / f"{review.review_id}.docx")


def render_governance_corpus(world: World, corpus_dir: Path) -> list[Path]:
    audit_dir = corpus_dir / "11_internal_audit"
    review_dir = corpus_dir / "12_management_review"
    paths = [render_internal_audit(world, audit, audit_dir) for audit in world.internal_audits]
    paths.extend(
        render_management_review(world, review, review_dir) for review in world.management_reviews
    )
    return paths
