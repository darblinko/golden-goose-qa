"""Word (.docx) renderers for controlled documents and record forms."""

from dataclasses import replace
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.shared import Pt

from gg_synthdata import ids
from gg_synthdata.model import Capa, ControlledDoc, Supplier, World
from gg_synthdata.render.common import FIXED_DOC_DATETIME, fmt_date, normalize_zip
from gg_synthdata.sop_content import ALL_PROCEDURES, ProcedureSpec

_SPEC_BY_DOC_ID: dict[str, ProcedureSpec] = {
    (ids.sop_id(s.number) if s.kind == "sop" else ids.wi_id(s.number)): s for s in ALL_PROCEDURES
}


def _new_document() -> DocumentType:
    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)
    return document


def _save(document: DocumentType, path: Path) -> Path:
    props = document.core_properties
    props.created = FIXED_DOC_DATETIME
    props.modified = FIXED_DOC_DATETIME
    props.last_modified_by = "Document Control"
    props.revision = 1
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    normalize_zip(path)
    return path


def _header_block(document: DocumentType, world: World, doc: ControlledDoc) -> None:
    document.add_heading(world.company, level=0)
    document.add_heading(f"{doc.doc_id} — {doc.title}", level=1)
    current = doc.current
    table = document.add_table(rows=2, cols=4)
    table.style = "Table Grid"
    header = ("Document Number", "Revision", "Effective Date", "Department")
    values = (doc.doc_id, current.rev, fmt_date(current.rev_date), doc.department)
    for i, text in enumerate(header):
        table.rows[0].cells[i].text = text
    for i, text in enumerate(values):
        table.rows[1].cells[i].text = text
    document.add_paragraph("")


def _revision_history(document: DocumentType, doc: ControlledDoc) -> None:
    document.add_heading("Revision History", level=2)
    table = document.add_table(rows=1 + len(doc.revisions), cols=5)
    table.style = "Table Grid"
    for i, text in enumerate(("Rev", "Date", "Description", "Author", "Approved By")):
        table.rows[0].cells[i].text = text
    for r, rev in enumerate(doc.revisions, start=1):
        cells = table.rows[r].cells
        cells[0].text = rev.rev
        cells[1].text = fmt_date(rev.rev_date)
        cells[2].text = rev.description
        cells[3].text = rev.author
        cells[4].text = rev.approver
    document.add_paragraph("")


def _references_section(document: DocumentType, world: World, doc: ControlledDoc) -> None:
    if not doc.references and not doc.regulation_refs:
        return
    document.add_heading("References", level=2)
    stale = {
        (d.evidence_ids[0], d.evidence_ids[1])
        for d in world.defects
        if d.kind == "stale_sop_reference"
    }
    for ref in doc.references:
        title = world.doc_index[ref].title if ref in world.doc_index else ""
        if (doc.doc_id, ref) in stale:
            document.add_paragraph(f"{ref}, {title}, Rev A", style="List Bullet")
        else:
            line = f"{ref}, {title}" if title else ref
            document.add_paragraph(line, style="List Bullet")
    for reg in doc.regulation_refs:
        document.add_paragraph(reg, style="List Bullet")


def render_procedure(world: World, doc: ControlledDoc, out_dir: Path) -> Path:
    spec = _SPEC_BY_DOC_ID[doc.doc_id]
    slug = doc.title.replace(" ", "_").replace("/", "-")
    path = out_dir / f"{doc.doc_id}_{slug}.docx"
    return _render_procedure_file(world, doc, spec, spec.steps, path)


def render_archived_procedure(world: World, doc: ControlledDoc, out_dir: Path) -> Path | None:
    """The immediately prior revision, retained as a quality record. Its body
    is one procedure step shorter and cites the regulatory dialect of its own
    era, so the archive genuinely differs from the effective revision."""
    if len(doc.revisions) < 2:
        return None
    spec = _SPEC_BY_DOC_ID[doc.doc_id]
    prior_revs = doc.revisions[:-1]
    era_refs = spec.iso_refs if prior_revs[-1].rev_date >= ids.QMSR_EFFECTIVE else spec.qsr_refs
    prior = replace(doc, revisions=prior_revs, regulation_refs=era_refs)
    steps = spec.steps[:-1] if len(spec.steps) > 1 else spec.steps
    slug = doc.title.replace(" ", "_").replace("/", "-")
    path = out_dir / f"{doc.doc_id}_{slug}_Rev_{prior.current.rev}.docx"
    return _render_procedure_file(world, prior, spec, steps, path)


def _render_procedure_file(
    world: World, doc: ControlledDoc, spec: ProcedureSpec, steps: tuple[str, ...], path: Path
) -> Path:
    document = _new_document()
    _header_block(document, world, doc)
    _revision_history(document, doc)
    document.add_heading("1. Purpose", level=2)
    document.add_paragraph(spec.purpose)
    document.add_heading("2. Scope", level=2)
    document.add_paragraph(spec.scope)
    _references_section(document, world, doc)
    document.add_heading("3. Procedure", level=2)
    for i, step in enumerate(steps, start=1):
        document.add_paragraph(f"3.{i}  {step}")
    document.add_heading("4. Records", level=2)
    for record in spec.records:
        document.add_paragraph(record, style="List Bullet")
    return _save(document, path)


def render_quality_manual(world: World, out_dir: Path) -> Path:
    doc = world.doc("QM-001")
    document = _new_document()
    _header_block(document, world, doc)
    _revision_history(document, doc)
    sections = (
        (
            "1. Scope",
            f"This manual defines the quality management system of {world.company}, "
            "a manufacturer of implantable infusion pumps (models MP-100 and MP-200). "
            "The QMS conforms to ISO 13485:2016 and the FDA Quality Management System "
            "Regulation, 21 CFR Part 820. Design and development, production, and "
            "servicing are within scope; there are no permitted exclusions.",
        ),
        (
            "2. Quality Policy",
            "Halvern Medical is committed to providing safe and "
            "effective implantable devices that meet customer and regulatory requirements, "
            "and to maintaining the effectiveness of the quality management system.",
        ),
        (
            "3. Organization",
            "The President has appointed the Director of Quality Assurance "
            "as management representative with authority to ensure QMS processes are "
            "established and maintained and to report on QMS performance at management review.",
        ),
        (
            "4. QMS Processes",
            "Documented procedures implement each QMS process. Document and "
            "record control is governed by SOP-001, design control by SOP-002, risk management "
            "by SOP-003, CAPA by SOP-004, nonconforming product by SOP-005, and complaint "
            "handling by SOP-006. Internal audits are conducted per SOP-014 and "
            "management review per SOP-015.",
        ),
        (
            "5. Product Realization",
            "Product is realized under device master records and "
            "device history records. Production operations are controlled by work "
            "instructions; sterilization is outsourced to a qualified supplier and released "
            "per parametric and biological indicator criteria.",
        ),
    )
    for title, body in sections:
        document.add_heading(title, level=2)
        document.add_paragraph(body)
    _references_section(document, world, doc)
    return _save(document, out_dir / "QM-001_Quality_Manual.docx")


def render_prs(world: World, out_dir: Path) -> Path:
    document = _new_document()
    document.add_heading(world.company, level=0)
    document.add_heading("PRS-100: Product Requirements Specification, HALVERN Pump", level=1)
    document.add_paragraph(
        "This specification states the design input requirements for the HALVERN "
        "implantable infusion pump family (MP-100, MP-200). Each requirement is "
        "verified per the traceability matrix TM-100."
    )
    table = document.add_table(rows=1 + len(world.requirements), cols=3)
    table.style = "Table Grid"
    for i, text in enumerate(("Requirement ID", "Category", "Requirement")):
        table.rows[0].cells[i].text = text
    for r, req in enumerate(world.requirements, start=1):
        cells = table.rows[r].cells
        cells[0].text = req.req_id
        cells[1].text = req.category
        cells[2].text = req.text
    return _save(document, out_dir / "PRS-100_Product_Requirements_Specification.docx")


def render_design_plan(world: World, out_dir: Path) -> Path:
    doc = world.doc("DP-100")
    document = _new_document()
    _header_block(document, world, doc)
    _revision_history(document, doc)
    vp = next(p for p in world.people if p.role == "VP of Engineering")
    sections = (
        (
            "1. Purpose",
            "This plan defines the design and development activities, "
            "responsibilities, and deliverables for the HALVERN pump family per SOP-002.",
        ),
        (
            "2. Team and Responsibilities",
            f"The design team is led by {vp.name} "
            f"({vp.role}). Design verification is owned by Quality Assurance; risk "
            "management activities follow RMP-100.",
        ),
        (
            "3. Design Stages",
            "Stages: planning, design input (PRS-100), design output "
            "(component specifications and drawings), verification (VTP/VTR series), "
            "validation, transfer, and changes. Stage exits require a documented design "
            "review with an independent reviewer.",
        ),
        (
            "4. Traceability",
            "Design inputs are traced to outputs and verification "
            "evidence in TM-100, maintained by Engineering and reviewed at each design review.",
        ),
    )
    for title, body in sections:
        document.add_heading(title, level=2)
        document.add_paragraph(body)
    _references_section(document, world, doc)
    return _save(document, out_dir / "DP-100_Design_and_Development_Plan.docx")


def _render_risk_doc(
    world: World, doc_id: str, bodies: tuple[tuple[str, str], ...], out_dir: Path, filename: str
) -> Path:
    doc = world.doc(doc_id)
    document = _new_document()
    _header_block(document, world, doc)
    _revision_history(document, doc)
    for title, body in bodies:
        document.add_heading(title, level=2)
        document.add_paragraph(body)
    _references_section(document, world, doc)
    return _save(document, out_dir / filename)


def render_risk_docs(world: World, out_dir: Path) -> list[Path]:
    rmp = (
        (
            "1. Purpose",
            "Defines the risk management activities for the HALVERN pump "
            "family across the product life cycle per ISO 14971:2019 and SOP-003.",
        ),
        (
            "2. Criteria for Risk Acceptability",
            "Risk acceptability is determined from "
            "the severity/probability matrix in Appendix A. Risks evaluated as "
            "unacceptable require risk control and re-evaluation before release.",
        ),
        (
            "3. Activities",
            "Hazard analysis, DFMEA-100, PFMEA-100, and clinical hazard "
            "review feed the risk analysis RA-100. Production and post-production "
            "information, including complaints and MDRs, is reviewed against the risk "
            "file per SOP-006.",
        ),
    )
    ra = (
        (
            "1. Method",
            "Hazards are analyzed per ISO 14971 with supporting failure mode "
            "analysis in DFMEA-100 (design) and PFMEA-100 (process).",
        ),
        (
            "5.1 Hazard: Loss of Infusion",
            "Causes include battery depletion, "
            "hermeticity loss, and electronics failure. Controls: design margins, 100% "
            "leak test, final flow and electrical test. Residual risk acceptable.",
        ),
        (
            "5.2 Hazard: Drug Over-Infusion",
            "Causes include firmware rate-control fault. "
            "Controls: hardware rate limiter, watchdog, fault injection testing. "
            "Residual risk acceptable.",
        ),
        (
            "5.3 Hazard: Loss of Telemetry",
            "Causes include coil failure and firmware "
            "defects. Controls: telemetry functional test at final acceptance. Residual "
            "risk acceptable.",
        ),
        (
            "5.4 Hazard: Infection / Biocompatibility",
            "Controls: ISO 10993 evaluation, "
            "validated EO sterilization at SAL 1e-6. Residual risk acceptable.",
        ),
        (
            "5.5 Hazard: Premature Battery Depletion",
            "Controls: supplier SPC, incoming "
            "acceptance sampling, longevity verification. Residual risk acceptable.",
        ),
        (
            "5.6 Hazard: Use Error",
            "Controls: human factors validation of programmer "
            "workflow, labeling. Residual risk acceptable.",
        ),
    )
    rmr = (
        (
            "1. Conclusion",
            "All identified risks have been reduced as far as possible "
            "and the overall residual risk is acceptable. Benefit-risk analysis supports "
            "release. Production and post-production data are trended quarterly; the "
            "risk file is updated when new hazards or increased occurrence rates are "
            "identified.",
        ),
        (
            "2. Traceability",
            "Risk control measures trace to verification evidence in "
            "TM-100 and to DFMEA/PFMEA detection and prevention controls.",
        ),
    )
    return [
        _render_risk_doc(world, "RMP-100", rmp, out_dir, "RMP-100_Risk_Management_Plan.docx"),
        _render_risk_doc(world, "RA-100", ra, out_dir, "RA-100_Risk_Analysis.docx"),
        _render_risk_doc(world, "RMR-100", rmr, out_dir, "RMR-100_Risk_Management_Report.docx"),
    ]


def render_capa_form(world: World, capa: Capa, out_dir: Path) -> Path:
    document = _new_document()
    document.add_heading(world.company, level=0)
    document.add_heading(f"Corrective and Preventive Action Record — {capa.capa_id}", level=1)
    rows = (
        ("CAPA Number", capa.capa_id),
        ("Date Opened", fmt_date(capa.opened)),
        ("Source", f"{capa.source_type.replace('_', ' ')} ({capa.source_id})"),
        ("Owner", capa.owner),
        ("Status", capa.status),
        ("Description", capa.description),
        ("Root Cause", capa.root_cause),
        ("Corrective Action", capa.corrective_action),
        ("Effectiveness Check Due", fmt_date(capa.effectiveness_due)),
        (
            "Effectiveness Check Completed",
            fmt_date(capa.effectiveness_completed)
            if capa.effectiveness_completed
            else "Not completed",
        ),
        ("Date Closed", fmt_date(capa.closed) if capa.closed else "Open"),
    )
    table = document.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    for i, (label, value) in enumerate(rows):
        table.rows[i].cells[0].text = label
        table.rows[i].cells[1].text = value
    document.add_paragraph("")
    document.add_paragraph(
        "Effectiveness verification per SOP-004: objective evidence that the action "
        "prevented recurrence must be recorded before closure."
    )
    return _save(document, out_dir / f"{capa.capa_id}.docx")


def render_supplier_audit(world: World, supplier: Supplier, out_dir: Path) -> Path:
    document = _new_document()
    document.add_heading(world.company, level=0)
    document.add_heading(f"Supplier Audit Summary Report — {supplier.audit_report_id}", level=1)
    findings = {
        "approved": "No major nonconformities. Two minor observations closed during the audit.",
        "conditional": "One major nonconformity in process change notification; supplier "
        "corrective action plan accepted. Approval is conditional pending verification "
        "at the next surveillance audit.",
    }[supplier.approval_status]
    rows = (
        ("Report Number", supplier.audit_report_id),
        ("Supplier", f"{supplier.name} ({supplier.supplier_id})"),
        ("Commodity", supplier.commodity),
        ("Audit Date", fmt_date(supplier.last_audit)),
        ("Audit Type", "On-site quality system audit per SOP-008"),
        ("Result", supplier.approval_status),
        ("Findings", findings),
    )
    table = document.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    for i, (label, value) in enumerate(rows):
        table.rows[i].cells[0].text = label
        table.rows[i].cells[1].text = value
    return _save(document, out_dir / f"{supplier.audit_report_id}_{supplier.supplier_id}.docx")


def render_word_corpus(world: World, corpus_dir: Path) -> list[Path]:
    qs_dir = corpus_dir / "01_quality_system"
    dhf_dir = corpus_dir / "02_design_history_file"
    risk_dir = corpus_dir / "03_risk_management"
    capa_dir = corpus_dir / "04_capa"
    supplier_dir = corpus_dir / "07_suppliers"

    paths = [render_quality_manual(world, qs_dir)]
    for doc in world.controlled_docs:
        if doc.doc_type in ("sop", "wi"):
            paths.append(render_procedure(world, doc, qs_dir))
            archived = render_archived_procedure(world, doc, qs_dir / "archive")
            if archived is not None:
                paths.append(archived)
    paths.append(render_prs(world, dhf_dir))
    paths.append(render_design_plan(world, dhf_dir))
    paths.extend(render_risk_docs(world, risk_dir))
    for capa in world.capas:
        paths.append(render_capa_form(world, capa, capa_dir))
    for supplier in world.suppliers:
        paths.append(render_supplier_audit(world, supplier, supplier_dir))
    return paths
