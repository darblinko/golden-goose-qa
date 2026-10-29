"""Builds the deterministic Halvern Medical world from a seed.

The world is the single source of truth: renderers emit documents from it and
the QA generator derives questions and answers from it, so evidence labels are
correct by construction. All randomness flows through one random.Random(seed).
"""

import random
from dataclasses import replace
from datetime import date, timedelta

from gg_synthdata import ids
from gg_synthdata.model import (
    Capa,
    Complaint,
    Component,
    ControlledDoc,
    ControlPlanRow,
    DesignOutput,
    FmeaRow,
    InternalAudit,
    ManagementReview,
    Mdr,
    Ncr,
    Person,
    Requirement,
    Revision,
    SeededDefect,
    Supplier,
    TrainingRecord,
    Traveler,
    TravelerStep,
    VerificationTest,
    World,
    ap_from_sod,
)
from gg_synthdata.sop_content import ALL_PROCEDURES, ProcedureSpec

COMPANY = "Halvern Medical, Inc."

PEOPLE: tuple[Person, ...] = (
    Person("Elena Vasquez", "Director of Quality Assurance", "EV", "Quality Assurance"),
    Person("Marcus Chen", "Regulatory Affairs Manager", "MC", "Regulatory Affairs"),
    Person("Priya Sharma", "VP of Engineering", "PS", "Engineering"),
    Person("David Okafor", "Manufacturing Manager", "DO", "Manufacturing"),
    Person("Sarah Lindqvist", "Quality Engineer", "SL", "Quality Assurance"),
    Person("James Whitfield", "Design Engineer", "JW", "Engineering"),
    Person("Aisha Mahmoud", "Supplier Quality Engineer", "AM", "Supply Chain"),
    Person("Tomas Herrera", "Production Supervisor", "TH", "Manufacturing"),
    Person("Rachel Nguyen", "Complaint Specialist", "RN", "Regulatory Affairs"),
    Person("Oliver Grant", "CAPA Coordinator", "OG", "Quality Assurance"),
    Person("Mei-Ling Wu", "Firmware Lead", "MW", "Engineering"),
    Person("Robert Castellanos", "Quality Control Inspector", "RC", "Quality Control"),
    Person("Hannah Beck", "Document Control Specialist", "HB", "Quality Assurance"),
    Person("Victor Adeyemi", "President", "VA", "Executive"),
)

COMPONENTS: tuple[Component, ...] = (
    Component("MP-100", "HALVERN Pump, 20 mL Reservoir", "Deliver programmed drug infusion", None),
    Component(
        "MP-200",
        "HALVERN Pump, 40 mL Reservoir",
        "Deliver infusion with extended refill interval",
        None,
    ),
    Component("HSG-100", "Titanium Enclosure", "Hermetic housing", "MP-100", "SUP-001"),
    Component(
        "HDR-200", "Catheter Port Assembly", "Catheter connection interface", "MP-100", "SUP-006"
    ),
    Component(
        "FT-210",
        "Feedthrough Assembly",
        "Hermetic fluid and signal pass-through",
        "HDR-200",
        "SUP-004",
    ),
    Component(
        "PCB-300",
        "Hybrid Circuit Assembly",
        "Pump drive, sensing, telemetry electronics",
        "MP-100",
        "SUP-003",
    ),
    Component("L2-310", "Telemetry Coil", "Inductive telemetry antenna", "PCB-300", "SUP-008"),
    Component("BAT-400", "Li/CFx Battery", "Primary power source", "MP-100", "SUP-002"),
    Component("FW-500", "Device Firmware", "Therapy control and telemetry logic", "MP-100", None),
)

SUPPLIERS_SPEC: tuple[tuple[str, str], ...] = (
    ("Titan Precision Machining", "Titanium enclosures"),
    ("NovaCell Power Systems", "Li/CFx batteries"),
    ("Cirrus Microelectronics", "Hybrid circuit fabrication"),
    ("Apex Feedthrough Technologies", "Hermetic feedthroughs"),
    ("SteriPro Services", "Contract EO sterilization"),
    ("Polymer Solutions Group", "Catheter port molding"),
    ("MedPack Systems", "Sterile barrier packaging"),
    ("Lumen Coil Works", "Telemetry coils"),
)

REQUIREMENTS_SPEC: tuple[tuple[str, str], ...] = (
    (
        "electrical",
        "The pump shall deliver basal infusion rates programmable from 0.05 to 1.00 mL/day in 0.01 mL/day steps.",
    ),
    ("electrical", "The pump shall deliver bolus doses programmable from 0.01 to 0.50 mL."),
    (
        "electrical",
        "Delivered volume shall be within 10% of the programmed volume over any 24 h period.",
    ),
    (
        "electrical",
        "The device shall detect catheter occlusion and raise an alarm within 4 hours of onset.",
    ),
    (
        "electrical",
        "Reservoir volume measurement shall be accurate to within 10% from 2 to 40 mL.",
    ),
    ("battery", "Projected device longevity shall be at least 10 years at nominal settings."),
    (
        "battery",
        "The device shall indicate elective replacement when remaining capacity reaches the ERI threshold.",
    ),
    ("battery", "Battery open-circuit voltage at acceptance shall be between 3.15 and 3.35 V."),
    (
        "telemetry",
        "The device shall support inductive telemetry at a range of at least 5 cm through tissue-equivalent media.",
    ),
    (
        "telemetry",
        "Telemetry sessions shall recover from link interruption without loss of committed programming.",
    ),
    (
        "mechanical",
        "The enclosure shall be hermetic with helium leak rate not exceeding 1e-9 atm-cc/s.",
    ),
    (
        "mechanical",
        "The device shall withstand a 1 m drop onto a hard surface without loss of function.",
    ),
    ("mechanical", "Device mass with an empty reservoir shall not exceed 175 g."),
    (
        "mechanical",
        "The feedthrough shall maintain insulation resistance above 100 megohms after thermal cycling.",
    ),
    (
        "biocompatibility",
        "All patient-contacting materials shall meet ISO 10993-1 requirements for a long-term implant.",
    ),
    ("sterilization", "The device shall be sterilized to a sterility assurance level of 1e-6."),
    (
        "sterilization",
        "EO and ECH residuals shall not exceed ISO 10993-7 limits for permanent implants.",
    ),
    (
        "software",
        "Firmware shall revert to the programmed minimum safe infusion rate upon detection of an unrecoverable fault.",
    ),
    ("software", "Firmware shall log device resets with cause codes retrievable by telemetry."),
    ("software", "Programming commands shall be verified by checksum before commitment."),
    (
        "emc",
        "The device shall meet ISO 14708-4 electromagnetic compatibility requirements for implantable infusion pumps.",
    ),
    (
        "emc",
        "The device shall maintain delivery accuracy in the presence of 50/60 Hz interference up to 10 V/m.",
    ),
    (
        "environmental",
        "The device shall operate within specification from 20 to 43 C body temperature range.",
    ),
    ("environmental", "Storage temperature range shall be -10 to 55 C without degradation."),
    ("labeling", "Labeling shall include UDI in both human-readable and AIDC formats."),
    (
        "labeling",
        "The patient identification card shall list device model, serial number, and implant date fields.",
    ),
    (
        "human_factors",
        "The programmer interface shall require confirmation before delivering any parameter change.",
    ),
    (
        "reliability",
        "The random failure rate shall not exceed 0.5% per device-year over the service life.",
    ),
    (
        "electrical",
        "The device shall tolerate 8 kV contact electrostatic discharge without permanent loss of function.",
    ),
    (
        "electrical",
        "Infusion shall be maintained during MRI conditional mode within labeled conditions.",
    ),
    (
        "mechanical",
        "Catheter connector retention force shall exceed 10 N after environmental conditioning.",
    ),
    ("telemetry", "Device memory interrogation shall complete within 60 seconds at nominal range."),
    ("battery", "Current drain at nominal settings shall not exceed 12 microamperes."),
    ("software", "Firmware shall prevent activation of unvalidated features via a feature lock."),
    (
        "sterilization",
        "Sterile barrier integrity shall be maintained for the labeled 24-month shelf life.",
    ),
    (
        "mechanical",
        "The catheter connector seal shall remain leak-free after 5 connect-disconnect cycles.",
    ),
    ("emc", "Telemetry emissions shall comply with FCC Part 15 and equivalent EU requirements."),
    (
        "reliability",
        "Solder and bond joints shall survive 500 thermal cycles from 0 to 70 C without failure.",
    ),
    (
        "human_factors",
        "Audible or vibratory patient alerts shall be perceivable per the human factors study.",
    ),
    ("labeling", "Instructions for use shall specify MRI conditional scanning parameters."),
)

TRAVELER_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("Kit Issue and Line Clearance", "SOP-010"),
    ("Wire Bond Hybrid Assembly", "WI-102"),
    ("Hybrid Electrical Test", "WI-104"),
    ("Enclosure Laser Weld", "WI-103"),
    ("Helium Leak Test", "WI-103"),
    ("Final Flow and Electrical Test", "WI-104"),
    ("Sterile Packaging", "SOP-017"),
    ("EO Sterilization Release", "WI-101"),
    ("DHR Review and Final Release", "SOP-010"),
)

COMPLAINT_CATEGORIES: tuple[tuple[str, str], ...] = (
    (
        "no_delivery",
        "Reservoir volume unchanged at refill visit; no drug delivered since prior visit.",
    ),
    (
        "premature_battery_depletion",
        "Battery reached ERI significantly earlier than projected longevity.",
    ),
    (
        "telemetry_failure",
        "Programmer unable to establish or maintain telemetry session with the device.",
    ),
    (
        "catheter_occlusion",
        "Occlusion alarm reported; delivered volume below programmed rate at refill.",
    ),
    ("packaging_damage", "Sterile barrier packaging received damaged or with compromised seal."),
    ("labeling_issue", "Labeling discrepancy reported between carton content and labeled model."),
)

_SERIOUS = {"no_delivery", "catheter_occlusion"}


def _rand_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randrange((end - start).days + 1))


def _pick_person(rng: random.Random, department: str | None = None) -> Person:
    pool = [p for p in PEOPLE if department is None or p.department == department]
    if not pool:
        pool = list(PEOPLE)
    return rng.choice(pool)


def _revisions_for(
    rng: random.Random, author: Person, approver: Person, force_post_qmsr: bool
) -> tuple[Revision, ...]:
    count = rng.randint(1, 4)
    revs = []
    start = _rand_date(rng, date(2021, 3, 1), date(2022, 12, 1))
    when = start
    for i in range(count):
        letter = chr(ord("A") + i)
        desc = (
            "Initial release."
            if i == 0
            else rng.choice(
                (
                    "Periodic review; clarified responsibilities.",
                    "Updated references and records section.",
                    "Incorporated audit finding; strengthened acceptance criteria.",
                    "Aligned terminology with current regulatory requirements.",
                )
            )
        )
        revs.append(Revision(letter, when, desc, author.name, approver.name))
        when = when + timedelta(days=rng.randint(200, 500))
    if force_post_qmsr and revs[-1].rev_date < ids.QMSR_EFFECTIVE:
        last = revs[-1]
        bumped = Revision(
            chr(ord(last.rev) + 1),
            _rand_date(rng, ids.QMSR_EFFECTIVE, date(2026, 6, 15)),
            "Updated regulatory citations for the FDA Quality Management System Regulation.",
            author.name,
            approver.name,
        )
        revs.append(bumped)
    # Clamp any generated dates into the past relative to the corpus date.
    revs = [
        r
        if r.rev_date < ids.WORLD_TODAY
        else Revision(
            r.rev, ids.WORLD_TODAY - timedelta(days=30), r.description, r.author, r.approver
        )
        for r in revs
    ]
    return tuple(revs)


def _procedure_doc(rng: random.Random, spec: ProcedureSpec, force_post_qmsr: bool) -> ControlledDoc:
    doc_id = ids.sop_id(spec.number) if spec.kind == "sop" else ids.wi_id(spec.number)
    author = _pick_person(rng, spec.department if spec.department != "Executive" else None)
    approver = next(p for p in PEOPLE if p.role == "Director of Quality Assurance")
    if author.name == approver.name:
        author = _pick_person(rng, "Engineering")
    revisions = _revisions_for(rng, author, approver, force_post_qmsr)
    era_refs = spec.iso_refs if revisions[-1].rev_date >= ids.QMSR_EFFECTIVE else spec.qsr_refs
    references = tuple(ids.sop_id(n) if n < 100 else ids.wi_id(n) for n in spec.reference_numbers)
    return ControlledDoc(
        doc_id=doc_id,
        title=spec.title,
        doc_type=spec.kind,
        department=spec.department,
        revisions=revisions,
        references=references,
        regulation_refs=era_refs,
    )


def _static_doc(
    rng: random.Random,
    doc_id: str,
    title: str,
    doc_type: str,
    department: str,
    references: tuple[str, ...] = (),
    regulation_refs: tuple[str, ...] = (),
) -> ControlledDoc:
    author = _pick_person(rng, department)
    approver = next(p for p in PEOPLE if p.role == "Director of Quality Assurance")
    return ControlledDoc(
        doc_id=doc_id,
        title=title,
        doc_type=doc_type,
        department=department,
        revisions=_revisions_for(rng, author, approver, force_post_qmsr=False),
        references=references,
        regulation_refs=regulation_refs,
    )


def _bump_past_first_revision(doc: ControlledDoc) -> ControlledDoc:
    """Append a deterministic second revision when a document has only one.

    DEF-005 declares that SOP-016 cites a superseded revision of WI-101, so
    WI-101's history must extend past the cited Rev A. Deterministic on
    purpose: consuming rng draws here would unpin every draw after it.
    """
    if len(doc.revisions) > 1:
        return doc
    first = doc.revisions[0]
    bump_date = min(first.rev_date + timedelta(days=400), ids.WORLD_TODAY - timedelta(days=30))
    bumped = Revision(
        chr(ord(first.rev) + 1),
        bump_date,
        "Revised EO load configuration diagrams and cycle parameters.",
        first.author,
        first.approver,
    )
    return replace(doc, revisions=(*doc.revisions, bumped))


def _build_design_space(
    rng: random.Random,
) -> tuple[
    tuple[Requirement, ...],
    tuple[DesignOutput, ...],
    tuple[VerificationTest, ...],
    tuple[str, ...],
]:
    requirements = tuple(
        Requirement(ids.req_id(i + 1), text, category, "Product Requirements Specification PRS-100")
        for i, (category, text) in enumerate(REQUIREMENTS_SPEC)
    )

    output_specs = (
        ("drawing", "Enclosure Assembly Drawing", ("mechanical",)),
        ("specification", "Enclosure Weld Specification", ("mechanical",)),
        ("specification", "Feedthrough Specification", ("mechanical",)),
        ("specification", "Hybrid Circuit Specification", ("electrical", "reliability")),
        ("specification", "Battery Specification", ("battery",)),
        ("specification", "Telemetry Subsystem Specification", ("telemetry", "emc")),
        ("specification", "Firmware Requirements Specification", ("software", "human_factors")),
        ("specification", "Sterilization Specification", ("sterilization",)),
        ("specification", "Labeling Specification", ("labeling",)),
        ("specification", "Biocompatibility Assessment Plan", ("biocompatibility",)),
        ("specification", "Environmental Requirements Specification", ("environmental",)),
        ("drawing", "Catheter Port Assembly Drawing", ("mechanical",)),
    )
    outputs = []
    for i, (kind, title, categories) in enumerate(output_specs):
        covered = tuple(r.req_id for r in requirements if r.category in categories)
        outputs.append(DesignOutput(ids.design_output_id(i + 1), title, kind, covered))

    tests = []
    gap_req = ids.req_id(17)  # seeded: EO residuals requirement never verified
    test_specs = (
        ("Infusion Rate Accuracy Verification", ("electrical",)),
        ("Occlusion Detection Verification", ("electrical",)),
        ("Longevity and Current Drain Verification", ("battery",)),
        ("Telemetry Range and Robustness Verification", ("telemetry",)),
        ("Hermeticity Verification", ("mechanical",)),
        ("Mechanical Integrity Verification", ("mechanical",)),
        ("EMC Verification per ISO 14708-4", ("emc",)),
        ("Environmental Verification", ("environmental",)),
        ("Firmware System Verification", ("software",)),
        ("Sterilization Validation", ("sterilization",)),
        ("Biocompatibility Evaluation", ("biocompatibility",)),
        ("Labeling and Human Factors Verification", ("labeling", "human_factors")),
        ("Reliability Demonstration", ("reliability",)),
    )
    for i, (title, categories) in enumerate(test_specs):
        covered = tuple(
            r.req_id for r in requirements if r.category in categories and r.req_id != gap_req
        )
        completed = _rand_date(rng, date(2023, 1, 15), date(2024, 6, 30))
        result = "pass" if rng.random() > 0.12 else "pass_with_deviation"
        tests.append(
            VerificationTest(
                ids.protocol_id(i + 1), ids.report_id(i + 1), title, covered, result, completed
            )
        )
    return requirements, tuple(outputs), tuple(tests), (gap_req,)


def _build_dfmea(rng: random.Random) -> tuple[FmeaRow, ...]:
    specs = (
        (
            "HSG-100 Enclosure",
            "Hermetic housing",
            "Weld seam crack",
            "Moisture ingress; electronics failure",
            "Laser power drift",
            9,
            3,
            4,
            "Validated weld schedule",
            "Helium leak test 100%",
        ),
        (
            "HSG-100 Enclosure",
            "Hermetic housing",
            "Case wall thinning",
            "Reduced structural margin",
            "Machining variation",
            6,
            2,
            3,
            "CNC process control",
            "Incoming dimensional inspection",
        ),
        (
            "FT-210 Feedthrough",
            "Fluid and signal pass-through",
            "Hermeticity loss at braze joint",
            "Moisture ingress; loss of infusion",
            "Braze void formation",
            9,
            4,
            5,
            "Braze process validation",
            "Sample leak test at supplier",
        ),
        (
            "FT-210 Feedthrough",
            "Fluid and signal pass-through",
            "Insulator crack",
            "Intermittent output",
            "Thermal shock during weld",
            8,
            3,
            4,
            "Weld heat sink fixture",
            "Post-weld electrical test",
        ),
        (
            "HDR-200 Catheter Port",
            "Catheter connection",
            "Connector latch fracture",
            "Catheter disconnection; drug leakage",
            "Over-insertion at implant",
            7,
            3,
            5,
            "Insertion depth marker; labeling",
            "Retention force qualification",
        ),
        (
            "HDR-200 Catheter Port",
            "Catheter connection",
            "Incomplete backfill",
            "Fluid path to feedthrough",
            "Injection process variation",
            8,
            3,
            4,
            "Validated molding parameters",
            "Visual inspection 100%",
        ),
        (
            "PCB-300 Hybrid",
            "Pump drive and sensing electronics",
            "Wire bond lift",
            "Loss of pump drive or sensing",
            "Bond parameter drift",
            9,
            3,
            3,
            "Shift pull-test monitoring",
            "Electrical test 100%",
        ),
        (
            "PCB-300 Hybrid",
            "Pump drive and sensing electronics",
            "Component solder fatigue",
            "Intermittent function",
            "Thermal cycling stress",
            8,
            2,
            4,
            "Design margin per IPC",
            "Reliability demonstration test",
        ),
        (
            "L2-310 Telemetry Coil",
            "Telemetry antenna",
            "Coil wire break",
            "Loss of telemetry",
            "Winding tension excess",
            5,
            3,
            4,
            "Tension-controlled winding",
            "Telemetry functional test",
        ),
        (
            "BAT-400 Battery",
            "Primary power",
            "Premature capacity loss",
            "Early ERI; shortened service",
            "Cathode lot variability",
            8,
            3,
            5,
            "Supplier SPC on cathode",
            "Acceptance OCV and capacity sample",
        ),
        (
            "BAT-400 Battery",
            "Primary power",
            "Internal short",
            "Rapid depletion; no delivery",
            "Separator defect",
            10,
            2,
            6,
            "Supplier 100% X-ray",
            "Incoming sample tear-down",
        ),
        (
            "FW-500 Firmware",
            "Therapy control",
            "Runaway infusion rate",
            "Drug overdose from excess delivery",
            "Timer register corruption",
            10,
            2,
            3,
            "Hardware rate limiter",
            "Static analysis; fault injection",
        ),
        (
            "FW-500 Firmware",
            "Therapy control",
            "Failure to revert to safe mode",
            "Loss of therapy after fault",
            "Unhandled exception path",
            9,
            3,
            4,
            "Watchdog + safe-state design",
            "Fault injection test suite",
        ),
        (
            "FW-500 Firmware",
            "Telemetry logic",
            "Corrupted programming commit",
            "Unintended parameter set",
            "Checksum bypass defect",
            9,
            2,
            3,
            "Command checksum + readback",
            "System test with induced errors",
        ),
        (
            "MP-100 System",
            "Deliver therapy",
            "No flow at implant",
            "Surgical delay; patient risk",
            "Latent assembly defect",
            9,
            2,
            3,
            "Final test coverage",
            "Pre-shipment interrogation",
        ),
        (
            "MP-100 System",
            "Deliver therapy",
            "MRI mode not engaging",
            "Therapy interruption during scan",
            "Mode logic defect",
            7,
            2,
            4,
            "MRI conditional design review",
            "MRI mode verification",
        ),
    )
    rows = []
    for i, (item, function, mode, effect, cause, s, o, d, prev, det) in enumerate(specs):
        correct = ap_from_sod(s, o, d)
        rows.append(
            FmeaRow(
                row_id=i + 1,
                item=item,
                function=function,
                failure_mode=mode,
                effect=effect,
                cause=cause,
                severity=s,
                occurrence=o,
                detection=d,
                ap_recorded=correct,
                ap_correct=correct,
                prevention_control=prev,
                detection_control=det,
                mitigation_refs=("RA-100",),
            )
        )
    # Seeded defect: the FT-210 hermeticity row is recorded one level low.
    target = rows[2]
    assert target.ap_correct == "H"
    rows[2] = FmeaRow(**{**target.__dict__, "ap_recorded": "M"})
    return tuple(rows)


def _build_pfmea(rng: random.Random) -> tuple[FmeaRow, ...]:
    specs = (
        (
            "Kit Issue",
            "Issue correct materials",
            "Wrong component lot issued",
            "Traceability loss",
            "Manual pick error",
            6,
            3,
            4,
            "Barcode-verified picking",
            "DHR review",
        ),
        (
            "Wire Bonding",
            "Attach bond wires",
            "Bond placed off pad",
            "Open circuit",
            "Operator alignment error",
            8,
            3,
            3,
            "Qualified operators; WI-102",
            "30x visual inspection",
        ),
        (
            "Wire Bonding",
            "Attach bond wires",
            "Weak bond adhesion",
            "Latent open circuit",
            "Surface contamination",
            8,
            3,
            4,
            "Plasma clean before bond",
            "Shift pull tests",
        ),
        (
            "Laser Weld",
            "Close enclosure",
            "Incomplete weld penetration",
            "Hermeticity failure",
            "Power setting drift",
            9,
            3,
            4,
            "Weld schedule verification",
            "100% helium leak test",
        ),
        (
            "Laser Weld",
            "Close enclosure",
            "Weld spatter inside case",
            "Electrical short risk",
            "Chamber contamination",
            8,
            2,
            5,
            "Chamber cleaning schedule",
            "Pre-weld inspection",
        ),
        (
            "Leak Test",
            "Verify hermeticity",
            "False accept",
            "Leaking device ships",
            "Calibration drift",
            9,
            2,
            5,
            "Daily calibrated leak standard",
            "Calibration program SOP-011",
        ),
        (
            "Final Test",
            "Verify device function",
            "Test escape",
            "Nonconforming device ships",
            "Fixture contact failure",
            9,
            2,
            4,
            "Fixture PM and verification",
            "Pre-shipment interrogation",
        ),
        (
            "Packaging",
            "Sterile barrier",
            "Incomplete seal",
            "Sterility loss",
            "Sealer temperature variation",
            9,
            3,
            4,
            "Validated sealer parameters",
            "Shift seal-strength samples",
        ),
        (
            "Packaging",
            "Sterile barrier",
            "Wrong label applied",
            "Misidentified device",
            "Label mix at station",
            7,
            2,
            3,
            "Single-label station control",
            "Final label verification",
        ),
        (
            "Sterilization",
            "Achieve SAL 1e-6",
            "Under-processed load",
            "Non-sterile product",
            "Chamber loading deviation",
            10,
            2,
            4,
            "Approved load diagrams WI-101",
            "BI and parametric release",
        ),
        (
            "DHR Review",
            "Confirm completeness",
            "Missing operation signature",
            "Unverified process step",
            "Manual review miss",
            6,
            4,
            4,
            "Checklist-driven review",
            "QA release audit",
        ),
    )
    rows = []
    for i, (item, function, mode, effect, cause, s, o, d, prev, det) in enumerate(specs):
        correct = ap_from_sod(s, o, d)
        rows.append(
            FmeaRow(
                row_id=i + 1,
                item=item,
                function=function,
                failure_mode=mode,
                effect=effect,
                cause=cause,
                severity=s,
                occurrence=o,
                detection=d,
                ap_recorded=correct,
                ap_correct=correct,
                prevention_control=prev,
                detection_control=det,
                realizes_dfmea_row=_PFMEA_REALIZES_DFMEA.get(i + 1),
            )
        )
    return tuple(rows)


# Sparse by design: assembly steps realize DFMEA-100 failure modes (wire bond
# rows realize "Wire bond lift", laser weld realizes "Weld seam crack");
# inspection, review, and packaging steps do not.
_PFMEA_REALIZES_DFMEA = {2: 7, 3: 7, 4: 1}


def _build_records(
    rng: random.Random, suppliers: tuple[Supplier, ...]
) -> tuple[tuple[Ncr, ...], tuple[Capa, ...], tuple[Complaint, ...], tuple[Mdr, ...]]:
    part_numbers = [c.part_number for c in COMPONENTS if c.parent is not None]
    ncr_descriptions = (
        "Dimensional nonconformance found at incoming inspection.",
        "Cosmetic defect exceeding workmanship criteria.",
        "Certificate of conformance missing required test data.",
        "Pull test below minimum during shift verification.",
        "Leak test failure at final acceptance.",
        "Solder joint void observed at inspection.",
        "Incorrect revision of component received.",
        "Label print quality below grade C.",
    )
    dispositions = ("use_as_is", "rework", "scrap", "return_to_vendor")

    ncrs: list[Ncr] = []
    per_year_ncr = {2024: 15, 2025: 18, 2026: 7}
    for year, count in per_year_ncr.items():
        for n in range(1, count + 1):
            opened = _rand_date(
                rng, date(year, 1, 2), date(year, 12, 20) if year < 2026 else date(2026, 6, 20)
            )
            part = rng.choice(part_numbers)
            component = next(c for c in COMPONENTS if c.part_number == part)
            closed = opened + timedelta(days=rng.randint(10, 120))
            is_closed = closed < ids.WORLD_TODAY and rng.random() > 0.15
            ncrs.append(
                Ncr(
                    ncr_id=ids.ncr_id(year, n),
                    opened=opened,
                    part_number=part,
                    description=rng.choice(ncr_descriptions),
                    disposition=rng.choice(dispositions),
                    status="closed" if is_closed else "open",
                    closed=closed if is_closed else None,
                    capa_id=None,  # linked below
                    supplier_id=component.supplier_id,
                )
            )

    complaints: list[Complaint] = []
    mdrs: list[Mdr] = []
    per_year_c = {2024: 25, 2025: 45, 2026: 10}
    mdr_counter = 1
    for year, count in per_year_c.items():
        for n in range(count):
            cid = ids.complaint_id(year, 101 + n)
            received = _rand_date(
                rng, date(year, 1, 5), date(year, 12, 22) if year < 2026 else date(2026, 6, 15)
            )
            category, description = rng.choice(COMPLAINT_CATEGORIES)
            model = rng.choice(("MP-100", "MP-200"))
            lot = ids.lot_number(year - rng.randint(0, 1), rng.randint(1, 60))
            reportable = category in _SERIOUS and rng.random() < 0.35
            mdr = None
            if reportable:
                mdr = ids.mdr_id(mdr_counter)
                mdr_counter += 1
                mdrs.append(
                    Mdr(
                        mdr_id=mdr,
                        complaint_id=cid,
                        submitted=received + timedelta(days=rng.randint(8, 28)),
                        event_type="malfunction" if rng.random() > 0.3 else "serious_injury",
                    )
                )
            closed = received + timedelta(days=rng.randint(20, 150))
            is_closed = closed < ids.WORLD_TODAY and rng.random() > 0.2
            complaints.append(
                Complaint(
                    complaint_id=cid,
                    received=received,
                    model=model,
                    lot=lot,
                    description=description,
                    failure_category=category,
                    investigation=(
                        "Returned device analyzed per WI-104; findings documented in the complaint file."
                        if rng.random() > 0.4
                        else "Device not returned; investigation based on clinical records and DHR review."
                    ),
                    risk_evaluated=True,
                    risk_reference=f"RA-100 §5.{rng.randint(1, 6)}",
                    mdr_id=mdr,
                    status="closed" if is_closed else "open",
                    closed=closed if is_closed else None,
                )
            )

    # Seeded defect: C-2025-0142 was never evaluated against the risk file.
    for i, c in enumerate(complaints):
        if c.complaint_id == "C-2025-0142":
            complaints[i] = Complaint(
                **{**c.__dict__, "risk_evaluated": False, "risk_reference": None}
            )
            break
    else:
        raise AssertionError("expected complaint C-2025-0142 to exist")

    capa_descriptions = (
        ("ncr", "Recurring incoming dimensional nonconformances from machining supplier."),
        ("ncr", "Repeat wire bond pull-test failures on second shift."),
        ("complaint", "Trend of telemetry failure complaints above alert limit."),
        ("complaint", "Premature battery depletion complaints exceeding reliability model."),
        ("internal_audit", "Audit finding: training records incomplete for revised procedures."),
        ("internal_audit", "Audit finding: environmental monitoring excursions not trended."),
    )
    capas: list[Capa] = []
    per_year_capa = {2024: 9, 2025: 11, 2026: 4}
    for year, count in per_year_capa.items():
        for n in range(1, count + 1):
            source_type, description = rng.choice(capa_descriptions)
            opened = _rand_date(
                rng, date(year, 1, 10), date(year, 12, 15) if year < 2026 else date(2026, 5, 30)
            )
            if source_type == "ncr":
                ncr_pool = [x for x in ncrs if x.opened <= opened]
                source_id = rng.choice(ncr_pool).ncr_id if ncr_pool else "NCR-2024-001"
            elif source_type == "complaint":
                complaint_pool = [x.complaint_id for x in complaints if x.received <= opened]
                source_id = rng.choice(complaint_pool) if complaint_pool else "C-2024-0101"
            else:
                source_id = f"AUD-{year}-{rng.randint(1, 2):02d}"
            eff_due = opened + timedelta(days=rng.randint(180, 320))
            closed = opened + timedelta(days=rng.randint(90, 200))
            is_closed = eff_due < ids.WORLD_TODAY - timedelta(days=30) and rng.random() > 0.3
            capas.append(
                Capa(
                    capa_id=ids.capa_id(year, n),
                    opened=opened,
                    source_type=source_type,
                    source_id=source_id,
                    description=description,
                    root_cause=rng.choice(
                        (
                            "Process parameter window not adequately controlled.",
                            "Procedure lacked explicit acceptance criteria.",
                            "Supplier process change was not communicated.",
                            "Training on revised procedure not completed before effective date.",
                        )
                    ),
                    corrective_action=rng.choice(
                        (
                            "Revised procedure with quantitative acceptance criteria and retrained staff.",
                            "Implemented automated verification at the affected operation.",
                            "Executed supplier corrective action and tightened incoming sampling.",
                            "Added effectiveness metric to monthly quality trending.",
                        )
                    ),
                    status="closed" if is_closed else "open",
                    closed=closed if is_closed else None,
                    effectiveness_due=eff_due,
                    effectiveness_completed=(
                        eff_due - timedelta(days=rng.randint(1, 25)) if is_closed else None
                    ),
                    owner=_pick_person(rng, "Quality Assurance").name,
                )
            )

    # Seeded defect: CAPA-2025-007 effectiveness check is overdue and unstarted.
    for i, capa in enumerate(capas):
        if capa.capa_id == "CAPA-2025-007":
            capas[i] = Capa(
                **{
                    **capa.__dict__,
                    "status": "open",
                    "closed": None,
                    "effectiveness_due": date(2026, 5, 15),
                    "effectiveness_completed": None,
                }
            )
            break
    else:
        raise AssertionError("expected CAPA-2025-007 to exist")

    # Link roughly a third of NCRs to CAPAs opened at or after the NCR.
    for i, ncr in enumerate(ncrs):
        if rng.random() < 0.3:
            capa_ids = [k.capa_id for k in capas if k.opened >= ncr.opened]
            if capa_ids:
                ncrs[i] = Ncr(**{**ncr.__dict__, "capa_id": rng.choice(capa_ids)})

    # Seeded walkable thread: CAPA-2025-014 sources from a real complaint and is
    # escalated to from a real NCR, giving record_thread() a multi-hop dossier to
    # traverse (complaint <- SOURCED_FROM - CAPA-2025-014 - ESCALATED_TO -> NCR).
    # Appended after the random draws above so it perturbs no other record.
    thread_capa_id = ids.capa_id(2025, 14)
    thread_complaint_id = ids.complaint_id(2025, 101)
    thread_ncr_id = ids.ncr_id(2025, 1)
    capas.append(
        Capa(
            capa_id=thread_capa_id,
            opened=date(2025, 3, 10),
            source_type="complaint",
            source_id=thread_complaint_id,
            description="Trend of telemetry failure complaints above alert limit.",
            root_cause="Procedure lacked explicit acceptance criteria.",
            corrective_action=(
                "Revised procedure with quantitative acceptance criteria and retrained staff."
            ),
            status="closed",
            closed=date(2025, 8, 15),
            effectiveness_due=date(2026, 1, 15),
            effectiveness_completed=date(2026, 1, 5),
            owner="Oliver Grant",
        )
    )
    for i, ncr in enumerate(ncrs):
        if ncr.ncr_id == thread_ncr_id:
            ncrs[i] = Ncr(**{**ncr.__dict__, "capa_id": thread_capa_id})
            break
    else:
        raise AssertionError(f"expected {thread_ncr_id} to exist for the seeded thread")

    return tuple(ncrs), tuple(capas), tuple(complaints), tuple(mdrs)


def _build_travelers(rng: random.Random) -> tuple[Traveler, ...]:
    travelers = []
    for n in range(1, 7):
        year = 2025 if n <= 4 else 2026
        lot = ids.lot_number(year, n * 7)
        started = _rand_date(rng, date(year, 1, 10), date(year, 5, 30))
        steps = []
        when = started
        for seq, (operation, sop_ref) in enumerate(TRAVELER_OPERATIONS, start=1):
            operator = _pick_person(rng, "Manufacturing")
            when = when + timedelta(days=rng.randint(1, 4))
            result = "accept"
            if n == 3 and operation == "Helium Leak Test":
                result = "reject"  # ties to an NCR narrative in the corpus
            steps.append(TravelerStep(seq, operation, sop_ref, operator.initials, when, result))
        travelers.append(
            Traveler(
                lot=lot,
                model="MP-100" if n % 2 else "MP-200",
                quantity=rng.randint(12, 40),
                started=started,
                steps=tuple(steps),
                scanned=n <= 3,
            )
        )
    return tuple(travelers)


def _build_training(
    rng: random.Random, docs: tuple[ControlledDoc, ...]
) -> tuple[TrainingRecord, ...]:
    records = []
    for doc in docs:
        if doc.doc_type not in ("sop", "wi"):
            continue
        pool = [p for p in PEOPLE if p.department in (doc.department, "Quality Assurance")]
        trained_people = rng.sample(pool, k=min(len(pool), rng.randint(3, 6)))
        current = doc.current
        for person in trained_people:
            trained = current.rev_date + timedelta(days=rng.randint(1, 21))
            if trained >= ids.WORLD_TODAY:
                trained = ids.WORLD_TODAY - timedelta(days=1)
            records.append(TrainingRecord(person.name, doc.doc_id, current.rev, trained))
    return tuple(records)


# Process areas an internal audit can cover, with the documents in scope.
# Every listed document exists as a corpus file.
_AUDIT_AREAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Document and Record Control", ("SOP-001",)),
    ("Design Control", ("SOP-002", "TM-100")),
    ("Risk Management", ("SOP-003", "RA-100")),
    ("Corrective and Preventive Action", ("SOP-004",)),
    ("Complaint Handling and Medical Device Reporting", ("SOP-006", "SOP-007")),
    ("Supplier Evaluation and Control", ("SOP-008", "ASL-100")),
    ("Production and Process Control", ("SOP-010", "WI-103")),
    ("Sterilization Process Control", ("SOP-012", "WI-101")),
    ("Training and Competency", ("SOP-013", "TRN-100")),
)

_AUDIT_OBSERVATIONS = (
    "Two obsolete forms found at a workstation; removed during the audit.",
    "One training record was filed under the employee's former department.",
    "Calibration label missing on a backup instrument not in active use.",
    "A reference copy of an external standard was not the current edition.",
)

_REVIEW_DECISIONS = (
    "Quality objectives for the period were met; no changes to the quality policy.",
    "Approved additional complaint-investigation resource for the next period.",
    "Directed that CAPA effectiveness metrics be added to monthly quality trending.",
    "Approved the internal audit schedule for the next period.",
    "Directed a supplier development review for conditionally approved suppliers.",
)


def _build_internal_audits(
    rng: random.Random, capas: tuple[Capa, ...]
) -> tuple[InternalAudit, ...]:
    """Two audits per year, covering every AUD-YYYY-NN id a CAPA can cite."""
    description_by_capa = {c.capa_id: c.description for c in capas}
    opened_by_capa = {c.capa_id: c.opened for c in capas}
    audits = []
    for year in (2024, 2025, 2026):
        windows = (
            (date(year, 1, 15), date(year, 3, 30)),
            (date(year, 8, 1), date(year, 10, 15))
            if year < 2026
            else (date(year, 4, 1), date(year, 5, 20)),
        )
        for n, (start, end) in enumerate(windows, start=1):
            audit_id = ids.internal_audit_id(year, n)
            capa_ids = tuple(
                sorted(
                    c.capa_id
                    for c in capas
                    if c.source_type == "internal_audit" and c.source_id == audit_id
                )
            )
            # An audit cannot postdate a CAPA it raised.
            if capa_ids:
                earliest_capa = min(opened_by_capa[capa_id] for capa_id in capa_ids)
                end = min(end, earliest_capa)
                start = min(start, end)
            picked = rng.sample(_AUDIT_AREAS, k=3)
            findings = (
                *(
                    f"{description_by_capa[capa_id]} Corrective action raised: {capa_id}."
                    for capa_id in capa_ids
                ),
                rng.choice(_AUDIT_OBSERVATIONS),
            )
            audits.append(
                InternalAudit(
                    audit_id=audit_id,
                    audit_date=_rand_date(rng, start, end),
                    lead_auditor=_pick_person(rng, "Quality Assurance").name,
                    areas=tuple(area for area, _ in picked),
                    scope_docs=tuple(dict.fromkeys(d for _, docs in picked for d in docs)),
                    findings=findings,
                    capa_ids=capa_ids,
                    result="Conforming with findings" if capa_ids else "Conforming",
                )
            )
    return tuple(audits)


def _build_management_reviews(
    rng: random.Random,
    audits: tuple[InternalAudit, ...],
    capas: tuple[Capa, ...],
    ncrs: tuple[Ncr, ...],
    complaints: tuple[Complaint, ...],
    mdrs: tuple[Mdr, ...],
) -> tuple[ManagementReview, ...]:
    """Semiannual reviews through 2025 H2 (the H1 2026 review is not yet due)."""
    chair = next(p for p in PEOPLE if p.role == "President")
    attendee_roles = (
        "Director of Quality Assurance",
        "Regulatory Affairs Manager",
        "VP of Engineering",
        "Manufacturing Manager",
        "CAPA Coordinator",
    )
    attendees = tuple(next(p.name for p in PEOPLE if p.role == role) for role in attendee_roles)
    reviews = []
    for year in (2024, 2025):
        halves = (
            (date(year, 1, 1), date(year, 6, 30)),
            (date(year, 7, 1), date(year, 12, 31)),
        )
        for half, (period_start, period_end) in enumerate(halves, start=1):
            reviews.append(
                ManagementReview(
                    review_id=ids.management_review_id(year, half),
                    meeting_date=period_end + timedelta(days=rng.randint(12, 30)),
                    period_start=period_start,
                    period_end=period_end,
                    chair=chair.name,
                    attendees=attendees,
                    capas_opened=sum(1 for c in capas if period_start <= c.opened <= period_end),
                    capas_closed=sum(
                        1 for c in capas if c.closed and period_start <= c.closed <= period_end
                    ),
                    ncrs_opened=sum(1 for n in ncrs if period_start <= n.opened <= period_end),
                    complaints_received=sum(
                        1 for c in complaints if period_start <= c.received <= period_end
                    ),
                    mdrs_submitted=sum(
                        1 for m in mdrs if period_start <= m.submitted <= period_end
                    ),
                    audit_ids=tuple(
                        a.audit_id for a in audits if period_start <= a.audit_date <= period_end
                    ),
                    decisions=tuple(rng.sample(_REVIEW_DECISIONS, k=2)),
                )
            )
    return tuple(reviews)


# Per-PFMEA-row control plan content: (characteristic, specification, reference).
# Index-aligned with the static PFMEA-100 row specs.
_CONTROL_PLAN_SPECS: tuple[tuple[str, str, str], ...] = (
    ("Component lot identity", "Issued lots match the DHR pick list", "SOP-010"),
    ("Bond placement", "Bond centered on pad per WI-102 figure 2", "WI-102"),
    ("Bond strength", "Wire pull strength >= 15 gf", "WI-102"),
    ("Enclosure hermeticity", "Helium leak rate <= 1e-8 atm-cc/s", "WI-103"),
    ("Weld seam alignment", "Seam gap <= 0.05 mm before welding", "WI-103"),
    ("Leak-test instrument calibration", "Calibration current per SOP-011", "SOP-011"),
    ("Electrical performance", "All parameters within PRS-100 limits", "WI-104"),
    ("Package seal strength", "Peel strength >= 1.5 lbf/in", "SOP-017"),
    ("Label content", "Label matches device model, lot, and UDI", "SOP-016"),
    ("Sterility assurance", "SAL 1e-6; biological indicator negative", "WI-101"),
    ("DHR completeness", "All operations signed and dated before release", "SOP-001"),
)

_REACTION_PLANS = (
    "Quarantine lot and disposition per SOP-005",
    "Stop the operation and notify Quality Engineering",
    "Rework per the governing work instruction and reinspect",
    "Hold lot for material review per SOP-005",
)

_CONTROL_FREQUENCIES = ("100%", "First article plus hourly", "1 per lot", "2 per shift")


def _build_control_plan(
    rng: random.Random, pfmea: tuple[FmeaRow, ...]
) -> tuple[ControlledDoc, tuple[ControlPlanRow, ...]]:
    doc = _static_doc(
        rng,
        "CTL-100",
        "Process Control Plan",
        "control_plan",
        "Manufacturing",
        references=("PFMEA-100", "SOP-010"),
        regulation_refs=("ISO 13485:2016 §7.5.1",),
    )
    rows = tuple(
        ControlPlanRow(
            row_id=i + 1,
            process_step=fmea_row.item,
            pfmea_row=fmea_row.row_id,
            characteristic=characteristic,
            specification=specification,
            control_method=fmea_row.detection_control,
            frequency=rng.choice(_CONTROL_FREQUENCIES),
            reference=reference,
            reaction_plan=rng.choice(_REACTION_PLANS),
        )
        for i, (fmea_row, (characteristic, specification, reference)) in enumerate(
            zip(pfmea, _CONTROL_PLAN_SPECS, strict=True)
        )
    )
    return doc, rows


def _build_clinical_docs(rng: random.Random) -> tuple[ControlledDoc, ...]:
    cip = _static_doc(
        rng,
        "CIP-100",
        "Clinical Investigation Plan",
        "clinical_plan",
        "Regulatory Affairs",
        references=("RA-100", "RMP-100", "SOP-006", "SOP-007"),
        regulation_refs=("ISO 14155:2020", "21 CFR Part 812"),
    )
    cer = _static_doc(
        rng,
        "CER-100",
        "Clinical Evaluation Report",
        "clinical_report",
        "Regulatory Affairs",
        references=("CIP-100", "RA-100", "RMR-100", "SOP-006"),
        regulation_refs=("ISO 14155:2020", "21 CFR Part 814"),
    )
    return (cip, cer)


def build_world(seed: int = 42) -> World:
    rng = random.Random(seed)

    # A stable subset of procedures is revised after the QMSR effective date so
    # the corpus exercises the QSR<->ISO 13485 synonym layer.
    post_qmsr_numbers = {1, 2, 4, 6, 7, 14, 22, 24}
    controlled: list[ControlledDoc] = [
        _static_doc(
            rng,
            "QM-001",
            "Quality Manual",
            "quality_manual",
            "Quality Assurance",
            references=("SOP-001", "SOP-002", "SOP-004", "SOP-006", "SOP-014", "SOP-015"),
            regulation_refs=("ISO 13485:2016", "21 CFR 820"),
        )
    ]
    controlled.extend(
        _procedure_doc(rng, spec, force_post_qmsr=spec.number in post_qmsr_numbers)
        for spec in ALL_PROCEDURES
    )
    controlled.extend(
        (
            _static_doc(
                rng,
                "DP-100",
                "Design and Development Plan, HALVERN Pump",
                "design_plan",
                "Engineering",
                references=("SOP-002", "TM-100"),
                regulation_refs=("ISO 13485:2016 Clause 7.3.2",),
            ),
            _static_doc(
                rng,
                "RMP-100",
                "Risk Management Plan, HALVERN Pump",
                "risk_plan",
                "Quality Assurance",
                references=("SOP-003",),
                regulation_refs=("ISO 14971:2019",),
            ),
            _static_doc(
                rng,
                "RA-100",
                "Risk Analysis, HALVERN Pump",
                "risk_analysis",
                "Quality Assurance",
                references=("RMP-100", "DFMEA-100", "PFMEA-100"),
                regulation_refs=("ISO 14971:2019",),
            ),
            _static_doc(
                rng,
                "RMR-100",
                "Risk Management Report, HALVERN Pump",
                "risk_report",
                "Quality Assurance",
                references=("RMP-100", "RA-100"),
                regulation_refs=("ISO 14971:2019",),
            ),
            _static_doc(
                rng,
                "TM-100",
                "Design Traceability Matrix, HALVERN Pump",
                "trace_matrix",
                "Engineering",
                references=("DP-100",),
            ),
            _static_doc(
                rng,
                "DFMEA-100",
                "Design FMEA, HALVERN Pump",
                "dfmea",
                "Engineering",
                references=("RA-100",),
            ),
            _static_doc(
                rng,
                "PFMEA-100",
                "Process FMEA, HALVERN Pump Assembly",
                "pfmea",
                "Manufacturing",
                references=("RA-100",),
            ),
            _static_doc(
                rng,
                "TRN-100",
                "Training Matrix",
                "training_matrix",
                "Human Resources",
                references=("SOP-013",),
            ),
        )
    )

    # DEF-005 needs WI-101 to have moved past the Rev A that SOP-016 cites.
    controlled = [
        _bump_past_first_revision(doc) if doc.doc_id == "WI-101" else doc for doc in controlled
    ]

    requirements, outputs, tests, trace_gaps = _build_design_space(rng)
    dfmea = _build_dfmea(rng)
    pfmea = _build_pfmea(rng)

    suppliers = tuple(
        Supplier(
            supplier_id=ids.supplier_id(i + 1),
            name=name,
            commodity=commodity,
            approval_status="approved" if i != 3 else "conditional",
            audit_report_id=ids.supplier_audit_id(2024 + (i % 2), i + 1),
            last_audit=_rand_date(rng, date(2024, 2, 1), date(2026, 4, 1)),
        )
        for i, (name, commodity) in enumerate(SUPPLIERS_SPEC)
    )

    ncrs, capas, complaints, mdrs = _build_records(rng, suppliers)
    travelers = _build_travelers(rng)
    training = _build_training(rng, tuple(controlled))

    # Governance, clinical, and control-plan entities draw from the rng after
    # every pre-existing draw so earlier IDs, revisions, and QA ground truth
    # stay pinned across seeds.
    internal_audits = _build_internal_audits(rng, capas)
    management_reviews = _build_management_reviews(
        rng, internal_audits, capas, ncrs, complaints, mdrs
    )
    clinical_docs = _build_clinical_docs(rng)
    control_plan_doc, control_plan_rows = _build_control_plan(rng, pfmea)

    ap_row = dfmea[2]
    defects = (
        SeededDefect(
            "DEF-001",
            "broken_trace_link",
            "REQ-017 (EO/ECH residual limits) has no verification evidence in the "
            "traceability matrix; no protocol or report covers it.",
            ("TM-100", "REQ-017"),
            "REQ-017 is not linked to any verification protocol or report in TM-100.",
        ),
        SeededDefect(
            "DEF-002",
            "ap_mismatch",
            "DFMEA-100 row 3 (FT-210 hermeticity loss at braze joint, S=9 O=4 D=5) "
            "records action priority M although the AIAG-VDA table yields H.",
            ("DFMEA-100",),
            f"Row 3 of DFMEA-100 records AP '{ap_row.ap_recorded}' but severity "
            f"{ap_row.severity}, occurrence {ap_row.occurrence}, detection "
            f"{ap_row.detection} require AP '{ap_row.ap_correct}'.",
        ),
        SeededDefect(
            "DEF-003",
            "overdue_effectiveness_check",
            "CAPA-2025-007 effectiveness check was due 2026-05-15 and has not been "
            "performed; the CAPA remains open.",
            ("CAPA-2025-007",),
            "CAPA-2025-007 effectiveness check due 2026-05-15 is overdue and not completed.",
        ),
        SeededDefect(
            "DEF-004",
            "complaint_without_risk_evaluation",
            "Complaint C-2025-0142 was never evaluated against the risk management "
            "file, contrary to SOP-006 step 3.",
            ("C-2025-0142", "SOP-006"),
            "C-2025-0142 has no risk file evaluation reference recorded.",
        ),
        SeededDefect(
            "DEF-005",
            "stale_sop_reference",
            "SOP-016 (Labeling Control) cites WI-101 Rev A although WI-101 is at a later revision.",
            ("SOP-016", "WI-101"),
            "SOP-016 references WI-101 Rev A; the current revision of WI-101 is newer.",
        ),
    )

    doc_index = {d.doc_id: d for d in controlled}
    doc_index.update({d.doc_id: d for d in (*clinical_docs, control_plan_doc)})
    return World(
        seed=seed,
        company=COMPANY,
        people=PEOPLE,
        components=COMPONENTS,
        controlled_docs=tuple(controlled),
        requirements=requirements,
        design_outputs=outputs,
        verification_tests=tests,
        trace_gaps=trace_gaps,
        dfmea_rows=dfmea,
        pfmea_rows=pfmea,
        ncrs=ncrs,
        capas=capas,
        complaints=complaints,
        mdrs=mdrs,
        suppliers=suppliers,
        travelers=travelers,
        training=training,
        internal_audits=internal_audits,
        management_reviews=management_reviews,
        clinical_docs=clinical_docs,
        control_plan_doc=control_plan_doc,
        control_plan_rows=control_plan_rows,
        defects=defects,
        doc_index=doc_index,
    )
