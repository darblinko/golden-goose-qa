"""Excel (.xlsx) renderers: trace matrix, FMEAs, training matrix, ASL."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from gg_synthdata.model import FmeaRow, World
from gg_synthdata.render.common import FIXED_DOC_DATETIME, fmt_date, normalize_zip

_HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
_BOLD = Font(bold=True)


def _save(wb: Workbook, path: Path) -> Path:
    props = wb.properties
    props.created = FIXED_DOC_DATETIME
    props.modified = FIXED_DOC_DATETIME
    props.creator = "Document Control"
    props.lastModifiedBy = "Document Control"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    normalize_zip(path)
    return path


def _title_rows(ws: Worksheet, world: World, doc_id: str, span: int) -> None:
    doc = world.doc(doc_id)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
    ws.cell(row=1, column=1, value=f"{world.company} — {doc_id} {doc.title}").font = _BOLD
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=span)
    ws.cell(
        row=2,
        column=1,
        value=f"Revision {doc.current.rev} — Effective {fmt_date(doc.current.rev_date)} — "
        f"Approved by {doc.current.approver}",
    )


def _header_row(ws: Worksheet, row: int, labels: tuple[str, ...]) -> None:
    for col, label in enumerate(labels, start=1):
        cell = ws.cell(row=row, column=col, value=label)
        cell.font = _BOLD
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="top")


_TRACE_HEADER_ROW = 4
_TRACE_GROUPS = (
    ("Requirement", 1, 3),
    ("Design", 4, 4),
    ("Verification", 5, 7),
    ("Status", 8, 8),
)


def _group_band(ws: Worksheet, row: int, groups: tuple[tuple[str, int, int], ...]) -> None:
    """AIAG/VDA-style grouped header band: a merged title over each column span,
    sitting above the flat field-header row."""
    for title, start, end in groups:
        if end > start:
            ws.merge_cells(start_row=row, start_column=start, end_row=row, end_column=end)
        cell = ws.cell(row=row, column=start, value=title)
        cell.font = _BOLD
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center")


def _merge_category_runs(ws: Worksheet, world: World, first_row: int) -> None:
    """Vertically merge the Category column down each contiguous run of like-
    category requirements — the grouped/continued layout auditors read as one
    subsystem band. The anchor keeps the value; continuation cells are cleared,
    so the parser must forward-fill the merge to recover each row's category."""
    reqs = world.requirements
    run_start = 0
    for i in range(1, len(reqs) + 1):
        if i < len(reqs) and reqs[i].category == reqs[run_start].category:
            continue
        if i - run_start >= 2:
            top, bottom = first_row + run_start, first_row + i - 1
            for r in range(top + 1, bottom + 1):
                ws.cell(row=r, column=2, value=None)
            ws.merge_cells(start_row=top, start_column=2, end_row=bottom, end_column=2)
        run_start = i


def render_trace_matrix(world: World, out_dir: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Traceability"
    labels = (
        "Requirement ID",
        "Category",
        "Requirement Text",
        "Design Output(s)",
        "Verification Protocol",
        "Verification Report",
        "Result",
        "Completed",
    )
    _title_rows(ws, world, "TM-100", len(labels))
    _group_band(ws, _TRACE_HEADER_ROW - 1, _TRACE_GROUPS)
    _header_row(ws, _TRACE_HEADER_ROW, labels)
    first_row = _TRACE_HEADER_ROW + 1
    for i, req in enumerate(world.requirements):
        row = first_row + i
        outputs = ", ".join(do.do_id for do in world.design_outputs if req.req_id in do.req_ids)
        tests = [t for t in world.verification_tests if req.req_id in t.req_ids]
        ws.cell(row=row, column=1, value=req.req_id)
        ws.cell(row=row, column=2, value=req.category)
        ws.cell(row=row, column=3, value=req.text)
        ws.cell(row=row, column=4, value=outputs)
        if tests:
            ws.cell(row=row, column=5, value=", ".join(t.protocol_id for t in tests))
            ws.cell(row=row, column=6, value=", ".join(t.report_id for t in tests))
            ws.cell(row=row, column=7, value=", ".join(t.result for t in tests))
            ws.cell(
                row=row,
                column=8,
                value=", ".join(fmt_date(t.completed) for t in tests if t.completed),
            )
    _merge_category_runs(ws, world, first_row)
    for col, width in zip("ABCDEFGH", (15, 14, 60, 18, 20, 20, 20, 24), strict=True):
        ws.column_dimensions[col].width = width
    return _save(wb, out_dir / "TM-100_Design_Traceability_Matrix.xlsx")


def _render_fmea(
    world: World, doc_id: str, rows: tuple[FmeaRow, ...], filename: str, out_dir: Path
) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "FMEA"
    labels = (
        "#",
        "Item",
        "Function",
        "Failure Mode",
        "Effect",
        "S",
        "Potential Cause",
        "O",
        "Prevention Control",
        "Detection Control",
        "D",
        "AP",
        "Risk File Ref",
        "DFMEA Ref",
    )
    _title_rows(ws, world, doc_id, len(labels))
    # AIAG-VDA style grouped header band with merged cells above the columns.
    groups = (
        ("Structure / Function", 1, 3),
        ("Failure Analysis", 4, 8),
        ("Risk Analysis", 9, 12),
        ("Optimization", 13, 14),
    )
    for title, start, end in groups:
        ws.merge_cells(start_row=3, start_column=start, end_row=3, end_column=end)
        cell = ws.cell(row=3, column=start, value=title)
        cell.font = _BOLD
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center")
    _header_row(ws, 4, labels)
    for i, r in enumerate(rows):
        row = 5 + i
        values = (
            r.row_id,
            r.item,
            r.function,
            r.failure_mode,
            r.effect,
            r.severity,
            r.cause,
            r.occurrence,
            r.prevention_control,
            r.detection_control,
            r.detection,
            r.ap_recorded,
            ", ".join(r.mitigation_refs),
            f"DFMEA-100 row {r.realizes_dfmea_row}" if r.realizes_dfmea_row else "",
        )
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value)
    widths = (5, 20, 20, 28, 30, 5, 28, 5, 26, 26, 5, 6, 14, 16)
    for letter, width in zip("ABCDEFGHIJKLMN", widths, strict=True):
        ws.column_dimensions[letter].width = width
    return _save(wb, out_dir / filename)


def render_training_matrix(world: World, out_dir: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Training Matrix"
    trained_docs = sorted({t.doc_id for t in world.training})
    _title_rows(ws, world, "TRN-100", len(trained_docs) + 1)
    _header_row(ws, 3, ("Employee", *trained_docs))
    by_key = {(t.person, t.doc_id): t for t in world.training}
    for i, person in enumerate(world.people):
        row = 4 + i
        ws.cell(row=row, column=1, value=f"{person.name} ({person.role})")
        for j, doc_id in enumerate(trained_docs, start=2):
            record = by_key.get((person.name, doc_id))
            if record:
                ws.cell(row=row, column=j, value=f"Rev {record.rev} {fmt_date(record.trained)}")
    ws.column_dimensions["A"].width = 42
    return _save(wb, out_dir / "TRN-100_Training_Matrix.xlsx")


def render_control_plan(world: World, out_dir: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Control Plan"
    labels = (
        "#",
        "Process Step",
        "PFMEA Ref",
        "Characteristic",
        "Specification",
        "Control Method",
        "Frequency",
        "Reference",
        "Reaction Plan",
    )
    _title_rows(ws, world, "CTL-100", len(labels))
    _header_row(ws, 3, labels)
    for i, row in enumerate(world.control_plan_rows):
        values = (
            row.row_id,
            row.process_step,
            f"PFMEA-100 row {row.pfmea_row}",
            row.characteristic,
            row.specification,
            row.control_method,
            row.frequency,
            row.reference,
            row.reaction_plan,
        )
        for col, value in enumerate(values, start=1):
            ws.cell(row=4 + i, column=col, value=value)
    widths = (5, 16, 18, 26, 40, 30, 20, 12, 44)
    for letter, width in zip("ABCDEFGHI", widths, strict=True):
        ws.column_dimensions[letter].width = width
    return _save(wb, out_dir / "CTL-100_Process_Control_Plan.xlsx")


def render_supplier_list(world: World, out_dir: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "ASL"
    labels = (
        "Supplier ID",
        "Supplier Name",
        "Commodity",
        "Approval Status",
        "Last Audit",
        "Audit Report",
    )
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(labels))
    ws.cell(row=1, column=1, value=f"{world.company} — Approved Supplier List").font = _BOLD
    _header_row(ws, 2, labels)
    for i, s in enumerate(world.suppliers):
        row = 3 + i
        values = (
            s.supplier_id,
            s.name,
            s.commodity,
            s.approval_status,
            fmt_date(s.last_audit),
            s.audit_report_id,
        )
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value)
    for letter, width in zip("ABCDEF", (12, 30, 28, 16, 14, 14), strict=True):
        ws.column_dimensions[letter].width = width
    return _save(wb, out_dir / "ASL-100_Approved_Supplier_List.xlsx")


def render_excel_corpus(world: World, corpus_dir: Path) -> list[Path]:
    dhf_dir = corpus_dir / "02_design_history_file"
    risk_dir = corpus_dir / "03_risk_management"
    return [
        render_trace_matrix(world, dhf_dir),
        _render_fmea(world, "DFMEA-100", world.dfmea_rows, "DFMEA-100_Design_FMEA.xlsx", risk_dir),
        _render_fmea(world, "PFMEA-100", world.pfmea_rows, "PFMEA-100_Process_FMEA.xlsx", risk_dir),
        render_control_plan(world, risk_dir),
        render_training_matrix(world, corpus_dir / "09_training"),
        render_supplier_list(world, corpus_dir / "07_suppliers"),
    ]
