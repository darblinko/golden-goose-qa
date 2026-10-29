"""Deterministic entity/edge extraction from parsed documents.

Extraction is a pure function of the parsed document plus the set of known
document keys: matrices and form fields produce typed nodes, edges, and
register rows; narrative text contributes REFERENCES edges via the id bank.
References to unknown ids are returned as dangling — surfaced, never turned
into edges, because a dangling reference is itself potential audit evidence.
"""

import re
from itertools import pairwise

from gg_common.actionpriority import compute_action_priority

from gg_ingestion.extract.idbank import find_ids, find_ids_with_correction, split_ids
from gg_ingestion.extract.model import DocExtraction, Edge, Node, Provenance, RegisterRow
from gg_ingestion.extract.records import (
    RecordExtractionError,
    docx_form_fields,
    id_in_parens,
    parse_form_date,
    pdf_form_fields,
    value_or_none,
)
from gg_ingestion.models import ParsedBlock, ParsedDocument

_TRAINING_CELL_RE = re.compile(r"^Rev\s+(?P<rev>[A-Z])\s+(?P<date>\d{2}-[A-Za-z]{3}-\d{4})$")
_PERSON_RE = re.compile(r"^(?P<name>[^()]+?)\s*\((?P<role>[^)]+)\)$")
_REV_HISTORY_FIRST_LINE = "Rev | Date | Description | Author | Approved By"
_CITED_REV_RE = re.compile(r"\bRev(?:ision)?\.?\s+(?P<rev>[A-Z][0-9]?)\b")

# Identifier families that never correspond to a corpus file; they are
# entities inside matrices, not documents, so they are not dangling refs.
_NON_DOCUMENT_FAMILIES = ("REQ-", "SUP-", "DO-", "VTP-")


def extract_document(parsed: ParsedDocument, known_doc_keys: frozenset[str]) -> DocExtraction:
    doc_type = parsed.meta.doc_type
    if doc_type == "trace_matrix":
        return _extract_trace_matrix(parsed, known_doc_keys)
    if doc_type in ("dfmea", "pfmea"):
        return _extract_fmea(parsed, known_doc_keys)
    if doc_type == "supplier_list":
        return _extract_supplier_list(parsed, known_doc_keys)
    if doc_type == "training_matrix":
        return _extract_training(parsed, known_doc_keys)
    if doc_type == "capa":
        return _extract_capa(parsed, known_doc_keys)
    if doc_type == "supplier_audit":
        return _extract_supplier_audit(parsed, known_doc_keys)
    if doc_type == "ncr":
        return _extract_ncr(parsed, known_doc_keys)
    if doc_type == "complaint":
        return _extract_complaint(parsed, known_doc_keys)
    if doc_type == "mdr":
        return _extract_mdr(parsed, known_doc_keys)
    if doc_type == "emdr":
        return _extract_emdr(parsed, known_doc_keys)
    if doc_type == "internal_audit":
        return _extract_internal_audit(parsed, known_doc_keys)
    if doc_type == "management_review":
        return _extract_management_review(parsed, known_doc_keys)
    if doc_type == "control_plan":
        return _extract_control_plan(parsed, known_doc_keys)
    if doc_type == "verification_report":
        return _extract_verification_report(parsed, known_doc_keys)
    return _extract_narrative(parsed, known_doc_keys)


def _cited_revisions(text: str) -> dict[str, str]:
    """Map document ids to the revision cited alongside them, line by line.

    Only a line naming exactly one document with exactly one revision token
    binds them ("WI-101, EO Sterilization Release, Rev A"); anything more
    ambiguous is left unbound — a missed citation is recoverable, a wrong
    one is not.
    """
    cited: dict[str, str] = {}
    for line in text.splitlines():
        ids = [i for i in find_ids(line) if not i.startswith(_NON_DOCUMENT_FAMILIES)]
        revs = _CITED_REV_RE.findall(line)
        if len(ids) == 1 and len(revs) == 1 and ids[0] not in cited:
            cited[ids[0]] = revs[0]
    return cited


class _Builder:
    """Accumulates extraction output with edge dedup by highest confidence."""

    def __init__(self, parsed: ParsedDocument, known_doc_keys: frozenset[str]) -> None:
        self.parsed = parsed
        self.doc_key = parsed.meta.doc_key
        self.known = known_doc_keys
        self.nodes: dict[tuple[str, str], Node] = {}
        self.edges: dict[tuple[str, str, str], Edge] = {}
        self.rows: list[RegisterRow] = []
        self.dangling: list[str] = []
        self.warnings: list[str] = []

    def node(self, label: str, key: str, **properties: object) -> None:
        existing = self.nodes.get((label, key))
        merged = {**existing.properties, **properties} if existing else dict(properties)
        self.nodes[(label, key)] = Node(label=label, key=key, properties=merged)

    def edge(
        self,
        rel_type: str,
        start: tuple[str, str],
        end: tuple[str, str],
        method: str,
        locator: str,
        **properties: object,
    ) -> None:
        provenance = Provenance(doc_key=self.doc_key, method=method, locator=locator)
        dedup_key = (rel_type, f"{start[0]}:{start[1]}", f"{end[0]}:{end[1]}")
        existing = self.edges.get(dedup_key)
        if existing and existing.provenance.confidence >= provenance.confidence:
            return
        self.edges[dedup_key] = Edge(
            rel_type=rel_type,
            start_label=start[0],
            start_key=start[1],
            end_label=end[0],
            end_key=end[1],
            provenance=provenance,
            properties=dict(properties),
        )

    def row(self, table: str, **values: object) -> None:
        self.rows.append(RegisterRow(table=table, values=values))

    def reference_edges(self, blocks: tuple[ParsedBlock, ...]) -> None:
        """REFERENCES edges from narrative text, registry-validated."""
        for block in blocks:
            if block.kind == "row":
                continue
            method = (
                "references_section"
                if "reference" in block.section_path.lower()
                else "inline_regex"
            )
            locator = (
                f"page {block.page}" if block.page else (block.section_path or "document body")
            )
            cited = _cited_revisions(block.text)
            for found in find_ids_with_correction(block.text, self.known):
                if found == self.doc_key:
                    continue  # footer/header self-reference
                if found.startswith(_NON_DOCUMENT_FAMILIES):
                    continue
                if found in self.known:
                    properties = {"cited_revision": cited[found]} if found in cited else {}
                    self.edge(
                        "REFERENCES",
                        ("Document", self.doc_key),
                        ("Document", found),
                        method,
                        locator,
                        **properties,
                    )
                else:
                    self.dangling.append(found)

    def document_edge_or_dangling(
        self, rel_type: str, target: str, method: str, locator: str, **properties: object
    ) -> None:
        if target in self.known:
            self.edge(
                rel_type,
                ("Document", self.doc_key),
                ("Document", target),
                method,
                locator,
                **properties,
            )
        else:
            self.dangling.append(target)

    def build(self) -> DocExtraction:
        return DocExtraction(
            doc_key=self.doc_key,
            doc_type=self.parsed.meta.doc_type,
            nodes=tuple(self.nodes.values()),
            edges=tuple(self.edges.values()),
            register_rows=tuple(self.rows),
            dangling_refs=tuple(dict.fromkeys(self.dangling)),
            warnings=tuple(self.warnings),
        )


def _extract_trace_matrix(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    for block in parsed.blocks:
        if block.kind != "row":
            continue
        req_id = block.fields.get("Requirement ID", "")
        if not req_id:
            continue
        locator = f"row {block.row_number}"
        b.node(
            "Requirement",
            req_id,
            category=block.fields.get("Category", ""),
            text=block.fields.get("Requirement Text", ""),
            source_doc_key=parsed.meta.doc_key,
            locator=locator,
        )
        outputs = split_ids(block.fields.get("Design Output(s)", ""))
        for do_id in outputs:
            b.node("DesignOutput", do_id)
            b.edge(
                "SATISFIES",
                ("DesignOutput", do_id),
                ("Requirement", req_id),
                "trace_matrix",
                locator,
            )
        protocols = split_ids(block.fields.get("Verification Protocol", ""))
        reports = split_ids(block.fields.get("Verification Report", ""))
        results = [r.strip() for r in block.fields.get("Result", "").split(",") if r.strip()]
        for i, report_id in enumerate(reports):
            b.edge(
                "VERIFIES",
                ("Document", report_id),
                ("Requirement", req_id),
                "trace_matrix",
                locator,
                protocol_id=protocols[i] if i < len(protocols) else None,
                result=results[i] if i < len(results) else None,
            )
            if report_id not in known:
                b.dangling.append(report_id)
        b.row(
            "requirement_trace",
            req_id=req_id,
            category=block.fields.get("Category", ""),
            requirement_text=block.fields.get("Requirement Text", ""),
            design_outputs=block.fields.get("Design Output(s)", ""),
            protocols=block.fields.get("Verification Protocol", ""),
            reports=block.fields.get("Verification Report", ""),
            results=block.fields.get("Result", ""),
            completed=block.fields.get("Completed", ""),
            has_verification=bool(reports),
            source_doc_key=parsed.meta.doc_key,
        )
    return b.build()


def _extract_fmea(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    for block in parsed.blocks:
        if block.kind != "row":
            continue
        try:
            row_id = int(block.fields.get("#", ""))
            severity = int(block.fields.get("S", ""))
            occurrence = int(block.fields.get("O", ""))
            detection = int(block.fields.get("D", ""))
        except ValueError:
            b.warnings.append(f"row {block.row_number}: non-numeric #/S/O/D, skipped")
            continue
        locator = f"row {block.row_number}"
        ap_recorded = block.fields.get("AP", "").strip()
        ap_computed = compute_action_priority(severity, occurrence, detection)
        key = f"{b.doc_key}:{row_id}"
        b.node(
            "FmeaRow",
            key,
            doc_key=b.doc_key,
            row_id=row_id,
            item=block.fields.get("Item", ""),
            function=block.fields.get("Function", ""),
            failure_mode=block.fields.get("Failure Mode", ""),
            effect=block.fields.get("Effect", ""),
            cause=block.fields.get("Potential Cause", ""),
            prevention_control=block.fields.get("Prevention Control", ""),
            detection_control=block.fields.get("Detection Control", ""),
            severity=severity,
            occurrence=occurrence,
            detection=detection,
            ap_recorded=ap_recorded,
            ap_computed=ap_computed,
            ap_mismatch=ap_recorded != ap_computed,
        )
        b.edge("HAS_ROW", ("Document", b.doc_key), ("FmeaRow", key), "fmea_sheet", locator)
        for ref in split_ids(block.fields.get("Risk File Ref", "")):
            if ref in known:
                b.edge("MITIGATED_BY", ("FmeaRow", key), ("Document", ref), "fmea_sheet", locator)
            else:
                b.dangling.append(ref)
        dfmea_ref = block.fields.get("DFMEA Ref", "").strip()
        if dfmea_ref:
            match = _DFMEA_REF_RE.match(dfmea_ref)
            if not match:
                b.warnings.append(f"{locator}: unparseable DFMEA Ref: {dfmea_ref!r}")
            elif match.group("doc") not in known:
                b.dangling.append(match.group("doc"))
            else:
                b.edge(
                    "REALIZED_IN",
                    ("FmeaRow", f"{match.group('doc')}:{int(match.group('row'))}"),
                    ("FmeaRow", key),
                    "fmea_sheet",
                    locator,
                )
        b.row(
            "fmea_row",
            doc_key=b.doc_key,
            row_id=row_id,
            item=block.fields.get("Item", ""),
            function=block.fields.get("Function", ""),
            failure_mode=block.fields.get("Failure Mode", ""),
            effect=block.fields.get("Effect", ""),
            cause=block.fields.get("Potential Cause", ""),
            prevention_control=block.fields.get("Prevention Control", ""),
            detection_control=block.fields.get("Detection Control", ""),
            severity=severity,
            occurrence=occurrence,
            detection=detection,
            ap_recorded=ap_recorded,
            ap_computed=ap_computed,
            ap_mismatch=ap_recorded != ap_computed,
            risk_file_refs=block.fields.get("Risk File Ref", ""),
        )
    return b.build()


def _extract_supplier_list(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    for block in parsed.blocks:
        if block.kind != "row":
            continue
        supplier_id = block.fields.get("Supplier ID", "")
        if not supplier_id:
            continue
        locator = f"row {block.row_number}"
        b.node(
            "Supplier",
            supplier_id,
            name=block.fields.get("Supplier Name", ""),
            commodity=block.fields.get("Commodity", ""),
            approval_status=block.fields.get("Approval Status", ""),
            last_audit=_iso(block.fields.get("Last Audit", "")),
        )
        b.edge(
            "LISTS", ("Document", b.doc_key), ("Supplier", supplier_id), "supplier_list", locator
        )
        audit_report = block.fields.get("Audit Report", "").strip()
        if audit_report:
            if audit_report in known:
                b.edge(
                    "AUDITS",
                    ("Document", audit_report),
                    ("Supplier", supplier_id),
                    "supplier_list",
                    locator,
                )
            else:
                b.dangling.append(audit_report)
        b.row(
            "supplier",
            supplier_id=supplier_id,
            name=block.fields.get("Supplier Name", ""),
            commodity=block.fields.get("Commodity", ""),
            approval_status=block.fields.get("Approval Status", ""),
            last_audit=parse_form_date(block.fields.get("Last Audit", "")),
            audit_report_id=audit_report or None,
            source_doc_key=b.doc_key,
        )
    return b.build()


def _extract_training(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    for block in parsed.blocks:
        if block.kind != "row":
            continue
        employee = block.fields.get("Employee", "")
        person = _PERSON_RE.match(employee)
        name = person.group("name").strip() if person else employee
        role = person.group("role").strip() if person else ""
        b.node("Person", name, role=role)
        locator = f"row {block.row_number}"
        for doc_key, cell in block.fields.items():
            if doc_key == "Employee":
                continue
            match = _TRAINING_CELL_RE.match(cell)
            if not match:
                b.warnings.append(f"{locator}: unparseable training cell for {doc_key}: {cell!r}")
                continue
            trained_on = parse_form_date(match.group("date"))
            if doc_key not in known:
                b.dangling.append(doc_key)
                continue
            b.edge(
                "TRAINED_ON",
                ("Person", name),
                ("Document", doc_key),
                "training_grid",
                locator,
                revision=match.group("rev"),
                trained_on=_iso(match.group("date")),
            )
            b.row(
                "training",
                person=name,
                role=role,
                doc_key=doc_key,
                revision=match.group("rev"),
                trained_on=trained_on,
                source_doc_key=b.doc_key,
            )
    return b.build()


def _extract_capa(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    fields = docx_form_fields(parsed)
    source = fields.get("Source", "")
    source_id = id_in_parens(source)
    source_type = source.split("(", 1)[0].strip()
    if source_id and split_ids(source_id):
        b.document_edge_or_dangling("SOURCED_FROM", source_id, "form_field", "Source")
    b.row(
        "capa",
        capa_id=fields.get("CAPA Number", b.doc_key),
        opened=parse_form_date(fields.get("Date Opened", "")),
        source_type=source_type,
        source_id=source_id or value_or_none(source),
        owner=fields.get("Owner", ""),
        status=fields.get("Status", ""),
        description=fields.get("Description", ""),
        root_cause=fields.get("Root Cause", ""),
        corrective_action=fields.get("Corrective Action", ""),
        effectiveness_due=parse_form_date(fields.get("Effectiveness Check Due", "")),
        effectiveness_completed=parse_form_date(fields.get("Effectiveness Check Completed", "")),
        closed=parse_form_date(fields.get("Date Closed", "")),
        source_doc_key=b.doc_key,
    )
    b.reference_edges(parsed.blocks)
    return b.build()


def _extract_supplier_audit(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    fields = docx_form_fields(parsed)
    supplier_field = fields.get("Supplier", "")
    supplier_id = id_in_parens(supplier_field)
    if supplier_id:
        b.node("Supplier", supplier_id, name=supplier_field.split("(", 1)[0].strip())
        b.edge(
            "AUDITS",
            ("Document", b.doc_key),
            ("Supplier", supplier_id),
            "form_field",
            "Supplier",
        )
    b.row(
        "supplier_audit",
        report_id=fields.get("Report Number", b.doc_key),
        supplier_id=supplier_id,
        audit_date=parse_form_date(fields.get("Audit Date", "")),
        audit_type=fields.get("Audit Type", ""),
        result=fields.get("Result", ""),
        findings=fields.get("Findings", ""),
        source_doc_key=b.doc_key,
    )
    b.reference_edges(parsed.blocks)
    return b.build()


def _extract_ncr(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    fields = pdf_form_fields(parsed)
    part = fields.get("Part Number", "")
    part_number, _, part_name = (p.strip() for p in part.partition("—"))
    supplier_id = id_in_parens(fields.get("Supplier", ""))
    capa_id = value_or_none(fields.get("Linked CAPA", ""), "None")
    if supplier_id:
        b.node("Supplier", supplier_id)
        b.edge(
            "FROM_SUPPLIER",
            ("Document", b.doc_key),
            ("Supplier", supplier_id),
            "form_field",
            "Supplier",
        )
    if capa_id:
        b.document_edge_or_dangling("ESCALATED_TO", capa_id, "form_field", "Linked CAPA")
    b.row(
        "ncr",
        ncr_id=fields.get("NCR Number", b.doc_key),
        opened=parse_form_date(fields.get("Date Opened", "")),
        part_number=part_number,
        part_name=part_name,
        supplier_id=supplier_id,
        description=fields.get("Description of Nonconformance", ""),
        disposition=fields.get("Disposition", ""),
        capa_id=capa_id,
        status=fields.get("Status", ""),
        closed=parse_form_date(fields.get("Date Closed", "")),
        source_doc_key=b.doc_key,
    )
    b.reference_edges(parsed.blocks)
    return b.build()


def _extract_complaint(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    fields = pdf_form_fields(parsed)
    risk_field = value_or_none(fields.get("Risk File Evaluation", ""), "—")
    mdr_id = value_or_none(fields.get("MDR Filed", ""), "Not reportable")
    if risk_field:
        for ref in find_ids(risk_field):
            b.document_edge_or_dangling(
                "EVALUATED_AGAINST", ref, "form_field", "Risk File Evaluation"
            )
    if mdr_id:
        b.document_edge_or_dangling("FILED_AS", mdr_id, "form_field", "MDR Filed")
    b.row(
        "complaint",
        complaint_id=fields.get("Complaint Number", b.doc_key),
        received=parse_form_date(fields.get("Date Received", "")),
        device_model=fields.get("Device Model", ""),
        lot=fields.get("Lot Number", ""),
        failure_category=fields.get("Failure Category", ""),
        description=fields.get("Description", ""),
        investigation=fields.get("Investigation Summary", ""),
        risk_evaluated=risk_field is not None,
        risk_reference=risk_field,
        mdr_id=mdr_id,
        status=fields.get("Status", ""),
        closed=parse_form_date(fields.get("Date Closed", "")),
        source_doc_key=b.doc_key,
    )
    b.reference_edges(parsed.blocks)
    return b.build()


def _extract_mdr(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    fields = pdf_form_fields(parsed)
    complaint_id = fields.get("Source Complaint", "").strip()
    if complaint_id:
        b.document_edge_or_dangling(
            "FROM_COMPLAINT", complaint_id, "form_field", "Source Complaint"
        )
    b.row(
        "mdr",
        mdr_id=fields.get("MDR Report Number", b.doc_key),
        complaint_id=complaint_id or None,
        submitted=parse_form_date(fields.get("Date Submitted to FDA", "")),
        event_type=fields.get("Event Type", ""),
        device_model=fields.get("Device Model", ""),
        lot=fields.get("Lot Number", ""),
        description=fields.get("Event Description", ""),
        source_doc_key=b.doc_key,
    )
    b.reference_edges(parsed.blocks)
    return b.build()


def _extract_emdr(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    """The eMDR export asserts the same event facts as the MDR summary it
    submits, so it contributes only the submission linkage to the graph —
    the MDR record itself stays the register's system of record."""
    b = _Builder(parsed, known)
    fields: dict[str, str] = {}
    for block in parsed.blocks:
        fields.update(block.fields)
    mdr_id = fields.get("MDR Record", "").strip()
    if mdr_id:
        b.document_edge_or_dangling("SUBMISSION_OF", mdr_id, "form_field", "MDR Record")
    complaint_id = fields.get("Source Complaint", "").strip()
    if complaint_id:
        b.document_edge_or_dangling(
            "FROM_COMPLAINT", complaint_id, "form_field", "Source Complaint"
        )
    b.reference_edges(parsed.blocks)
    return b.build()


def _extract_internal_audit(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    """Audit reports contribute graph linkage only: the CAPA side of each
    finding already lives in the CAPA register, which cites its source audit."""
    b = _Builder(parsed, known)
    fields = docx_form_fields(parsed)
    for doc_key in split_ids(fields.get("Documents in Scope", "")):
        b.document_edge_or_dangling("AUDITS", doc_key, "form_field", "Documents in Scope")
    b.reference_edges(parsed.blocks)
    return b.build()


def _extract_management_review(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    fields = docx_form_fields(parsed)
    for audit_id in split_ids(fields.get("Internal Audits Conducted", "")):
        b.document_edge_or_dangling("REVIEWED", audit_id, "form_field", "Internal Audits Conducted")
    b.reference_edges(parsed.blocks)
    return b.build()


_PFMEA_REF_RE = re.compile(r"^(?P<doc>PFMEA-[0-9]{2,4})\s+row\s+(?P<row>[0-9]+)$")
_DFMEA_REF_RE = re.compile(r"^(?P<doc>DFMEA-[0-9]{2,4})\s+row\s+(?P<row>[0-9]+)$")


def _extract_control_plan(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    """The control plan contributes graph linkage only: each row pins the
    PFMEA row it controls, so the FMEA register stays the system of record."""
    b = _Builder(parsed, known)
    for block in parsed.blocks:
        if block.kind != "row":
            continue
        locator = f"row {block.row_number}"
        pfmea_ref = block.fields.get("PFMEA Ref", "").strip()
        match = _PFMEA_REF_RE.match(pfmea_ref)
        if not match:
            b.warnings.append(f"{locator}: unparseable PFMEA Ref: {pfmea_ref!r}")
        elif match.group("doc") not in known:
            b.dangling.append(match.group("doc"))
        else:
            b.edge(
                "CONTROLLED_BY",
                ("FmeaRow", f"{match.group('doc')}:{int(match.group('row'))}"),
                ("Document", b.doc_key),
                "control_plan",
                locator,
                characteristic=block.fields.get("Characteristic", ""),
                control_method=block.fields.get("Control Method", ""),
                frequency=block.fields.get("Frequency", ""),
            )
        for ref in split_ids(block.fields.get("Reference", "")):
            b.document_edge_or_dangling("REFERENCES", ref, "control_plan", locator)
    return b.build()


def _extract_verification_report(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    fields = pdf_form_fields(parsed)
    protocol = fields.get("Protocol", "").strip()
    result = fields.get("Result", "").strip()
    for req_id in split_ids(fields.get("Requirements Verified", "")):
        b.node("Requirement", req_id)
        b.edge(
            "VERIFIES",
            ("Document", b.doc_key),
            ("Requirement", req_id),
            "form_field",
            "Requirements Verified",
            protocol_id=protocol or None,
            result=result or None,
        )
    b.reference_edges(parsed.blocks)
    return b.build()


def _extract_narrative(parsed: ParsedDocument, known: frozenset[str]) -> DocExtraction:
    b = _Builder(parsed, known)
    _revision_history(b, parsed)
    b.reference_edges(parsed.blocks)
    return b.build()


def _revision_history(b: _Builder, parsed: ParsedDocument) -> None:
    for block in parsed.blocks:
        if block.kind != "table" or not block.text.startswith(_REV_HISTORY_FIRST_LINE):
            continue
        revisions = []
        for line in block.text.splitlines()[1:]:
            cells = [c.strip() for c in line.split(" | ")]
            if len(cells) < 5 or not cells[0]:
                continue
            revisions.append(cells)
        for cells in revisions:
            rev, rev_date, description, author, approved_by = cells[:5]
            key = f"{b.doc_key}:{rev}"
            b.node(
                "DocumentRevision",
                key,
                doc_key=b.doc_key,
                revision=rev,
                effective_date=_iso(rev_date),
                description=description,
                author=author,
                approved_by=approved_by,
            )
            b.edge(
                "HAS_REVISION",
                ("Document", b.doc_key),
                ("DocumentRevision", key),
                "revision_table",
                f"rev {rev}",
            )
        for earlier, later in pairwise(revisions):
            b.edge(
                "SUPERSEDES",
                ("DocumentRevision", f"{b.doc_key}:{later[0]}"),
                ("DocumentRevision", f"{b.doc_key}:{earlier[0]}"),
                "revision_table",
                f"rev {later[0]}",
            )
        return


def _iso(raw: str) -> str | None:
    """ISO string for an optional metadata date (supplier last-audit, training
    date, revision date). Unlike a record's status dates, these are soft: an
    absent or malformed value degrades to None rather than failing the whole
    document's extraction."""
    try:
        parsed = parse_form_date(raw)
    except RecordExtractionError:
        return None
    return parsed.isoformat() if parsed else None
