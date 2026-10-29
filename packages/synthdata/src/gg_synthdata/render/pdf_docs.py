"""Born-digital PDF renderers (reportlab) for QMS records.

reportlab's invariant mode pins the PDF producer string, document ID, and
timestamps so output is byte-deterministic.
"""

from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from gg_synthdata.model import Complaint, Mdr, Ncr, Traveler, VerificationTest, World
from gg_synthdata.render.common import fmt_date

rl_config.invariant = 1

_STYLES = getSampleStyleSheet()
_BODY = _STYLES["BodyText"]
_TITLE = ParagraphStyle("FormTitle", parent=_STYLES["Heading1"], fontSize=14, spaceAfter=6)
_COMPANY = ParagraphStyle("Company", parent=_STYLES["Heading2"], fontSize=11, spaceAfter=2)

_GRID = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.85, 0.88, 0.95)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]
)
_ROW_GRID = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.85, 0.88, 0.95)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]
)


def _form_pdf(
    world: World,
    title: str,
    fields: tuple[tuple[str, str], ...],
    path: Path,
    note: str | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=letter, topMargin=0.7 * inch)
    data = [[label, Paragraph(value, _BODY)] for label, value in fields]
    table = Table(data, colWidths=[2.0 * inch, 4.6 * inch])
    table.setStyle(_GRID)
    story = [
        Paragraph(world.company, _COMPANY),
        Paragraph(title, _TITLE),
        Spacer(1, 8),
        table,
    ]
    if note:
        story.extend([Spacer(1, 10), Paragraph(note, _BODY)])
    doc.build(story)
    return path


def render_ncr(world: World, ncr: Ncr, out_dir: Path) -> Path:
    component = next(c for c in world.components if c.part_number == ncr.part_number)
    supplier = next((s for s in world.suppliers if s.supplier_id == ncr.supplier_id), None)
    fields = (
        ("NCR Number", ncr.ncr_id),
        ("Date Opened", fmt_date(ncr.opened)),
        ("Part Number", f"{ncr.part_number} — {component.name}"),
        ("Supplier", f"{supplier.name} ({supplier.supplier_id})" if supplier else "Internal"),
        ("Description of Nonconformance", ncr.description),
        ("Disposition", ncr.disposition.replace("_", " ")),
        ("Linked CAPA", ncr.capa_id or "None"),
        ("Status", ncr.status),
        ("Date Closed", fmt_date(ncr.closed) if ncr.closed else "Open"),
    )
    return _form_pdf(
        world,
        f"Nonconforming Product Report — {ncr.ncr_id}",
        fields,
        out_dir / f"{ncr.ncr_id}.pdf",
        note="Dispositioned per SOP-005. Use-as-is and rework dispositions require "
        "documented engineering justification.",
    )


def render_complaint(world: World, complaint: Complaint, out_dir: Path) -> Path:
    risk_field = (complaint.risk_reference or "—") if complaint.risk_evaluated else "—"
    fields = (
        ("Complaint Number", complaint.complaint_id),
        ("Date Received", fmt_date(complaint.received)),
        ("Device Model", complaint.model),
        ("Lot Number", complaint.lot),
        ("Failure Category", complaint.failure_category.replace("_", " ")),
        ("Description", complaint.description),
        ("Investigation Summary", complaint.investigation),
        ("Risk File Evaluation", risk_field),
        ("MDR Filed", complaint.mdr_id or "Not reportable"),
        ("Status", complaint.status),
        ("Date Closed", fmt_date(complaint.closed) if complaint.closed else "Open"),
    )
    return _form_pdf(
        world,
        f"Complaint Record — {complaint.complaint_id}",
        fields,
        out_dir / f"{complaint.complaint_id}.pdf",
        note="Handled per SOP-006. Each complaint is evaluated for MDR reportability "
        "and against the risk management file.",
    )


def render_mdr(world: World, mdr: Mdr, out_dir: Path) -> Path:
    complaint = next(c for c in world.complaints if c.complaint_id == mdr.complaint_id)
    fields = (
        ("MDR Report Number", mdr.mdr_id),
        ("Source Complaint", mdr.complaint_id),
        ("Date Submitted to FDA", fmt_date(mdr.submitted)),
        ("Event Type", mdr.event_type.replace("_", " ")),
        ("Device Model", complaint.model),
        ("Lot Number", complaint.lot),
        ("Event Description", complaint.description),
    )
    return _form_pdf(
        world,
        f"Medical Device Report Summary — {mdr.mdr_id}",
        fields,
        out_dir / f"{mdr.mdr_id}.pdf",
        note="Submitted per SOP-007 within the timelines of 21 CFR Part 803.",
    )


def render_vtr(world: World, test: VerificationTest, out_dir: Path) -> Path:
    fields = (
        ("Report Number", test.report_id),
        ("Protocol", test.protocol_id),
        ("Title", test.title),
        ("Requirements Verified", ", ".join(test.req_ids)),
        ("Result", test.result.replace("_", " ")),
        ("Date Completed", fmt_date(test.completed) if test.completed else "In progress"),
    )
    return _form_pdf(
        world,
        f"Verification Test Report — {test.report_id}",
        fields,
        out_dir / f"{test.report_id}.pdf",
        note="Executed per the referenced protocol under SOP-002 design control. "
        "Deviations, if any, are documented and dispositioned within the report.",
    )


def render_traveler_pdf(world: World, traveler: Traveler, out_dir: Path) -> Path:
    path = out_dir / f"DHR_{traveler.lot}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=letter, topMargin=0.7 * inch)
    header = [
        Paragraph(world.company, _COMPANY),
        Paragraph(f"Device History Record — Lot {traveler.lot}", _TITLE),
        Paragraph(
            f"Model: {traveler.model}    Quantity: {traveler.quantity}    "
            f"Started: {fmt_date(traveler.started)}",
            _BODY,
        ),
        Spacer(1, 8),
    ]
    rows = [["Seq", "Operation", "Procedure", "Operator", "Date", "Result"]]
    for step in traveler.steps:
        rows.append(
            [
                str(step.seq),
                step.operation,
                step.sop_ref,
                step.operator_initials,
                fmt_date(step.completed),
                step.result,
            ]
        )
    table = Table(
        rows, colWidths=[0.5 * inch, 2.4 * inch, 0.9 * inch, 0.8 * inch, 1.1 * inch, 0.8 * inch]
    )
    table.setStyle(_ROW_GRID)
    doc.build(
        [
            *header,
            table,
            Spacer(1, 10),
            Paragraph(
                "All operations complete and records reviewed per SOP-010 before final release.",
                _BODY,
            ),
        ]
    )
    return path


def render_pdf_corpus(world: World, corpus_dir: Path) -> list[Path]:
    dhf_dir = corpus_dir / "02_design_history_file"
    ncr_dir = corpus_dir / "05_nonconformance"
    complaint_dir = corpus_dir / "06_complaints"
    dhr_dir = corpus_dir / "08_production_records"

    paths = [render_vtr(world, t, dhf_dir) for t in world.verification_tests]
    paths.extend(render_ncr(world, n, ncr_dir) for n in world.ncrs)
    paths.extend(render_complaint(world, c, complaint_dir) for c in world.complaints)
    paths.extend(render_mdr(world, m, complaint_dir) for m in world.mdrs)
    paths.extend(render_traveler_pdf(world, t, dhr_dir) for t in world.travelers if not t.scanned)
    return paths
