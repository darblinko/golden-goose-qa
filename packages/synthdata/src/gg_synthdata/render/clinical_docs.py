"""Word (.docx) renderers for the clinical documents: CIP-100 and CER-100."""

from pathlib import Path

from gg_synthdata.model import World
from gg_synthdata.render.word_docs import (
    _header_block,
    _new_document,
    _references_section,
    _revision_history,
    _save,
)


def render_clinical_plan(world: World, out_dir: Path) -> Path:
    doc = world.doc("CIP-100")
    document = _new_document()
    _header_block(document, world, doc)
    _revision_history(document, doc)
    document.add_heading("1. Purpose", level=2)
    document.add_paragraph(
        "This Clinical Investigation Plan defines the objectives, design, and "
        "conduct of the pre-market clinical investigation of the HALVERN "
        "implantable infusion pump family (models MP-100 and MP-200)."
    )
    document.add_heading("2. Scope", level=2)
    document.add_paragraph(
        "This plan applies to all investigational sites, investigators, and "
        "subjects enrolled in the HALVERN pivotal study. It governs data "
        "collection from first implant through the 12-month follow-up visit."
    )
    document.add_heading("3. Objectives and Endpoints", level=2)
    document.add_paragraph(
        "Primary effectiveness endpoint: delivered volume within 15 percent of "
        "programmed volume at the 6-month refill visit. Primary safety endpoint: freedom "
        "from system-related complications at 6 months of at least 92 percent."
    )
    document.add_heading("4. Study Design", level=2)
    document.add_paragraph(
        "Prospective, multi-center, single-arm investigation with performance "
        "goals derived from published implantable pump trials. A minimum of 120 "
        "subjects will be enrolled across up to 10 investigational sites."
    )
    document.add_heading("5. Risk Considerations", level=2)
    document.add_paragraph(
        "Anticipated adverse device effects are drawn from the risk analysis "
        "RA-100 and managed under the risk management plan RMP-100. Residual "
        "risks disclosed to subjects are listed in the informed consent form."
    )
    document.add_heading("6. Adverse Event Reporting", level=2)
    document.add_paragraph(
        "Investigators report adverse events to the sponsor within 3 working "
        "days. The sponsor evaluates each event for complaint handling per "
        "SOP-006 and for regulatory reportability per SOP-007."
    )
    _references_section(document, world, doc)
    document.add_heading("7. Records", level=2)
    document.add_paragraph(
        "Case report forms, device accountability logs, and monitoring reports "
        "are retained in the clinical trial master file per SOP-001."
    )
    return _save(document, out_dir / "CIP-100_Clinical_Investigation_Plan.docx")


def render_clinical_report(world: World, out_dir: Path) -> Path:
    doc = world.doc("CER-100")
    document = _new_document()
    _header_block(document, world, doc)
    _revision_history(document, doc)
    document.add_heading("1. Purpose", level=2)
    document.add_paragraph(
        "This Clinical Evaluation Report summarizes the clinical evidence "
        "supporting the safety and performance of the HALVERN implantable "
        "infusion pump family and concludes on its benefit-risk profile."
    )
    document.add_heading("2. Device Description", level=2)
    document.add_paragraph(
        "The evaluation covers model MP-100 (20 mL reservoir) and model MP-200 "
        "(40 mL reservoir), including the titanium enclosure, catheter port assembly, "
        "and device firmware described in the design history file."
    )
    document.add_heading("3. Clinical Data Sources", level=2)
    document.add_paragraph(
        "Evidence comprises the pivotal investigation conducted under CIP-100, "
        "a systematic literature review of equivalent implantable infusion systems, and "
        "post-market surveillance data from the complaint handling process."
    )
    document.add_heading("4. Post-Market Experience", level=2)
    document.add_paragraph(
        f"Through the current reporting period the complaint handling process "
        f"has received {len(world.complaints)} complaints across both models, "
        f"of which {len(world.mdrs)} met reportability criteria per SOP-007 "
        f"and were submitted as medical device reports."
    )
    document.add_heading("5. Benefit-Risk Conclusion", level=2)
    document.add_paragraph(
        "The clinical evidence demonstrates that the HALVERN family performs "
        "as intended and that residual risks documented in the risk management "
        "report RMR-100 are acceptable when weighed against the therapeutic "
        "benefit of targeted drug infusion. The overall benefit-risk profile is "
        "favorable and continued market availability is supported."
    )
    _references_section(document, world, doc)
    document.add_heading("6. Records", level=2)
    document.add_paragraph(
        "This report and its supporting appendices are retained as part of the "
        "clinical evaluation file per SOP-001 and reviewed at each scheduled "
        "update of the risk management report."
    )
    return _save(document, out_dir / "CER-100_Clinical_Evaluation_Report.docx")


def render_clinical_corpus(world: World, corpus_dir: Path) -> list[Path]:
    clinical_dir = corpus_dir / "13_clinical"
    return [
        render_clinical_plan(world, clinical_dir),
        render_clinical_report(world, clinical_dir),
    ]
