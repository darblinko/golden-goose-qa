"""Content catalog for controlled procedures.

Each entry defines one SOP/WI: title, owning department, purpose, scope,
procedure steps, and the QSR-era vs QMSR-era regulatory citations. world.py
turns these into ControlledDoc objects with revision histories; the Word
renderer expands them into full documents.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcedureSpec:
    number: int
    kind: str  # sop | wi
    title: str
    department: str
    purpose: str
    scope: str
    steps: tuple[str, ...]
    records: tuple[str, ...]
    qsr_refs: tuple[str, ...]
    iso_refs: tuple[str, ...]
    reference_numbers: tuple[int, ...] = ()  # other SOP/WI numbers cited


SOPS: tuple[ProcedureSpec, ...] = (
    ProcedureSpec(
        1,
        "sop",
        "Document and Record Control",
        "Quality Assurance",
        "Define controls for creation, review, approval, distribution, and "
        "obsolescence of quality system documents and records.",
        "Applies to all controlled documents and quality records at Halvern "
        "Medical, including electronic records in the eQMS.",
        (
            "Draft documents using the controlled template and assign a document "
            "number from the document register.",
            "Route the draft for review by the process owner and Quality Assurance.",
            "Obtain approval signatures before release; the approver must be "
            "independent of the author where practical.",
            "Release the document in the eQMS and update the master document list.",
            "Train affected personnel before the effective date per SOP-013.",
            "Retire superseded revisions and retain them as quality records; only "
            "the current revision may appear at points of use.",
            "Retain quality records for the lifetime of the device plus two years, "
            "and no less than five years from the date of release.",
        ),
        ("Master document list", "Document change orders", "Obsolete document log"),
        ("21 CFR 820.40", "21 CFR 820.180"),
        ("ISO 13485:2016 Clause 4.2.4", "ISO 13485:2016 Clause 4.2.5"),
        (13,),
    ),
    ProcedureSpec(
        2,
        "sop",
        "Design Control",
        "Engineering",
        "Establish design and development planning, inputs, outputs, review, "
        "verification, validation, transfer, and change control for Halvern devices.",
        "Applies to the HALVERN implantable infusion pump family and all "
        "design changes to released devices.",
        (
            "Prepare a design and development plan identifying stages, "
            "responsibilities, and design review gates.",
            "Capture design inputs from intended use, user needs, regulatory "
            "requirements, and risk management outputs; resolve ambiguity before "
            "approval.",
            "Record design outputs in drawings, specifications, and the device "
            "master record; each output must trace to an input.",
            "Hold staged design reviews with an independent reviewer present.",
            "Verify design outputs against inputs using approved protocols; record "
            "results in verification reports.",
            "Validate the design against user needs on production-equivalent units, "
            "including software validation per SOP-021.",
            "Maintain the design traceability matrix TM-100 linking requirements to "
            "outputs and verification evidence.",
            "Control design changes through change control per SOP-024, including "
            "regression of affected verification.",
        ),
        ("Design history file", "Design review minutes", "Traceability matrix"),
        ("21 CFR 820.30",),
        ("ISO 13485:2016 Clause 7.3",),
        (21, 24, 3),
    ),
    ProcedureSpec(
        3,
        "sop",
        "Risk Management",
        "Quality Assurance",
        "Define the risk management process for identification, evaluation, "
        "control, and monitoring of risks across the device lifecycle.",
        "Applies to all Halvern devices and accessories from concept through "
        "post-market surveillance.",
        (
            "Prepare a risk management plan defining scope, criteria for risk "
            "acceptability, and verification of risk controls.",
            "Perform hazard analysis and estimate risk for each hazardous "
            "situation using severity and probability criteria in the plan.",
            "Perform design and process FMEAs; assign action priority per the "
            "AIAG-VDA action priority table.",
            "Implement risk controls in the order: inherent safety by design, "
            "protective measures, information for safety.",
            "Verify implementation and effectiveness of each risk control and "
            "record residual risk.",
            "Evaluate overall residual risk against the plan criteria and document "
            "the conclusion in the risk management report.",
            "Review production and post-production information, including "
            "complaints per SOP-006, against the risk file at defined intervals.",
        ),
        ("Risk management plan", "Risk analysis", "Risk management report"),
        ("21 CFR 820.30(g)",),
        ("ISO 14971:2019", "ISO 13485:2016 Clause 7.1"),
        (6,),
    ),
    ProcedureSpec(
        4,
        "sop",
        "Corrective and Preventive Action",
        "Quality Assurance",
        "Establish the CAPA process for investigating and eliminating causes of "
        "actual and potential nonconformities.",
        "Applies to CAPAs arising from nonconforming product, complaints, audits, "
        "and data analysis.",
        (
            "Open a CAPA when trending, a nonconformance, a complaint "
            "investigation, or an audit finding indicates a systemic cause.",
            "Define the problem statement with objective evidence and containment "
            "actions where product is at risk.",
            "Investigate root cause using a structured method (5 Whys, fishbone, "
            "or fault tree) proportionate to risk.",
            "Define corrective actions addressing the root cause and verify they "
            "do not adversely affect the device.",
            "Implement actions through change control and verify implementation.",
            "Define an effectiveness check with objective criteria and a due "
            "date; a CAPA may not close until effectiveness is confirmed.",
            "Escalate overdue effectiveness checks to management review.",
        ),
        ("CAPA records", "Effectiveness check evidence", "CAPA trend reports"),
        ("21 CFR 820.100",),
        ("ISO 13485:2016 Clause 8.5.2", "ISO 13485:2016 Clause 8.5.3"),
        (5, 6, 14),
    ),
    ProcedureSpec(
        5,
        "sop",
        "Control of Nonconforming Product",
        "Quality Assurance",
        "Define identification, segregation, evaluation, and disposition of "
        "product that does not conform to specified requirements.",
        "Applies to incoming, in-process, and finished product at all Halvern facilities.",
        (
            "Identify and segregate nonconforming product immediately; apply a "
            "hold tag and move to the MRB cage where practical.",
            "Open a nonconformance report (NCR) describing the requirement, the "
            "observed condition, and the affected quantity and lots.",
            "The material review board evaluates the nonconformance and assigns a "
            "disposition: use-as-is, rework, scrap, or return to vendor.",
            "Use-as-is dispositions on implantable product require a documented "
            "risk assessment and Quality Assurance approval.",
            "Rework must follow an approved rework instruction and include "
            "re-inspection of the affected characteristics.",
            "Evaluate whether the nonconformance warrants a CAPA per SOP-004 and "
            "record the linkage on the NCR.",
            "Trend NCRs quarterly by part number and supplier and report to management review.",
        ),
        ("NCR records", "MRB minutes", "Rework records"),
        ("21 CFR 820.90",),
        ("ISO 13485:2016 Clause 8.3",),
        (4,),
    ),
    ProcedureSpec(
        6,
        "sop",
        "Complaint Handling",
        "Regulatory Affairs",
        "Establish receipt, evaluation, investigation, and closure of complaints "
        "concerning Halvern devices.",
        "Applies to all communications alleging deficiencies in identity, "
        "quality, durability, reliability, safety, or performance of a released "
        "device.",
        (
            "Log every complaint in the complaint register within two business "
            "days of receipt with device model, serial or lot, and event description.",
            "Evaluate each complaint for MDR reportability per SOP-007 within the "
            "regulatory clock.",
            "Evaluate each complaint against the risk management file per SOP-003 "
            "and record the risk file reference on the complaint record.",
            "Investigate device-related complaints; where a returned device is "
            "available, perform decontamination and analysis per WI-104.",
            "Determine whether the complaint indicates a nonconformance and open "
            "an NCR or CAPA per SOP-005 and SOP-004 as warranted.",
            "Respond to the complainant where appropriate and close the complaint "
            "with a documented justification.",
            "Trend complaints monthly by failure category and report to management review.",
        ),
        ("Complaint register", "Complaint investigation records", "Reply letters"),
        ("21 CFR 820.198",),
        ("ISO 13485:2016 Clause 8.2.2",),
        (7, 3, 5, 4),
    ),
    ProcedureSpec(
        7,
        "sop",
        "Medical Device Reporting",
        "Regulatory Affairs",
        "Define evaluation and submission of medical device reports to FDA and "
        "other competent authorities.",
        "Applies to events involving Halvern devices that may meet reporting "
        "thresholds in any market where the device is sold.",
        (
            "Evaluate every complaint for reportability: death, serious injury, or "
            "malfunction that could cause or contribute to death or serious injury.",
            "Submit MDRs to FDA within 30 calendar days, or within 5 work days "
            "where remedial action is required to prevent unreasonable risk.",
            "Use the eMDR electronic submission format; retain the ACK "
            "confirmation with the report.",
            "Record the MDR decision rationale on the complaint record, including "
            "decisions not to report.",
            "Maintain MDR event files linking the complaint, investigation, and submitted report.",
            "Evaluate reportable events against the risk management file and "
            "consider field action per SOP-019.",
        ),
        ("MDR event files", "eMDR submissions and ACKs", "Reportability decisions"),
        ("21 CFR 803",),
        ("21 CFR 803", "ISO 13485:2016 Clause 8.2.3"),
        (6, 19),
    ),
    ProcedureSpec(
        8,
        "sop",
        "Supplier Evaluation and Control",
        "Supply Chain",
        "Establish evaluation, approval, and monitoring of suppliers of "
        "materials, components, and services affecting product quality.",
        "Applies to all suppliers on the approved supplier list, including "
        "critical-component and sterilization service suppliers.",
        (
            "Classify suppliers by risk based on the impact of their product or "
            "service on device safety and performance.",
            "Evaluate new suppliers by questionnaire, and by on-site or remote "
            "audit for critical suppliers, before approval.",
            "Record approved suppliers, their scope, and status on the approved supplier list.",
            "Establish quality agreements with critical suppliers covering change "
            "notification and record access.",
            "Monitor supplier performance through incoming inspection results per "
            "SOP-009 and supplier corrective action requests.",
            "Re-audit critical suppliers on a three-year cycle or after "
            "significant quality events.",
            "Escalate persistent supplier issues to conditional status and "
            "restrict new orders pending corrective action.",
        ),
        ("Approved supplier list", "Supplier audit reports", "Quality agreements"),
        ("21 CFR 820.50",),
        ("ISO 13485:2016 Clause 7.4",),
        (9,),
    ),
    ProcedureSpec(
        9,
        "sop",
        "Incoming Inspection",
        "Quality Control",
        "Define receipt, inspection, and release of incoming materials and components.",
        "Applies to all production materials received at the Halvern facility.",
        (
            "Verify each receipt against the purchase order and the packing list; "
            "quarantine material pending inspection.",
            "Inspect per the component inspection plan using calibrated equipment "
            "per SOP-011; sample per the sampling plan in SOP-020.",
            "Verify certificates of conformance and, for critical components, "
            "certificates of analysis against specification.",
            "Record results in the incoming inspection log; release conforming "
            "material to stock with an accept label.",
            "Route nonconforming receipts to the NCR process per SOP-005 and "
            "notify Supply Chain for supplier follow-up per SOP-008.",
            "Feed inspection results into supplier performance monitoring.",
        ),
        ("Incoming inspection log", "Certificates of conformance", "Accept labels"),
        ("21 CFR 820.80(b)",),
        ("ISO 13485:2016 Clause 7.4.3", "ISO 13485:2016 Clause 8.2.4"),
        (11, 20, 5, 8),
    ),
    ProcedureSpec(
        10,
        "sop",
        "Production and Process Control",
        "Manufacturing",
        "Define controls for manufacturing operations to ensure devices conform to specifications.",
        "Applies to all production of the HALVERN implantable infusion pump family.",
        (
            "Manufacture only against a released device master record and an "
            "approved production order.",
            "Issue a device history record traveler for each lot; record each "
            "operation, operator, date, and result at completion.",
            "Perform line clearance before starting a new lot to prevent mix-ups.",
            "Execute special processes (wire bonding per WI-102, laser welding per "
            "WI-103) using qualified operators and validated parameters.",
            "Perform in-process inspections at defined hold points; nonconforming "
            "units follow SOP-005.",
            "Perform final acceptance testing per WI-104 before release to sterilization.",
            "Release each lot only after device history record review by Quality "
            "Assurance confirms all operations and acceptance activities are "
            "complete.",
        ),
        ("Device history records", "Line clearance records", "Process logs"),
        ("21 CFR 820.70", "21 CFR 820.184"),
        ("ISO 13485:2016 Clause 7.5.1", "ISO 13485:2016 Clause 7.5.8"),
        (5, 12),
    ),
    ProcedureSpec(
        11,
        "sop",
        "Calibration and Preventive Maintenance",
        "Manufacturing",
        "Establish calibration and maintenance of measuring and production equipment.",
        "Applies to all equipment whose performance affects product quality or "
        "measurement decisions.",
        (
            "Maintain an equipment register with calibration interval, tolerance, "
            "and traceability requirements for each instrument.",
            "Calibrate measuring equipment against standards traceable to NIST at "
            "defined intervals.",
            "Label equipment with calibration status; remove overdue equipment "
            "from service immediately.",
            "Evaluate the impact on product of any out-of-tolerance condition "
            "found at calibration and open an NCR per SOP-005 where product may "
            "be affected.",
            "Perform preventive maintenance per the equipment maintenance schedule "
            "and record completion.",
        ),
        ("Equipment register", "Calibration certificates", "Maintenance logs"),
        ("21 CFR 820.72",),
        ("ISO 13485:2016 Clause 7.6",),
        (5,),
    ),
    ProcedureSpec(
        12,
        "sop",
        "Sterilization Process Control",
        "Manufacturing",
        "Define controls for ethylene oxide sterilization of finished devices "
        "by the contract sterilizer.",
        "Applies to EO sterilization of the HALVERN implantable infusion pump "
        "family performed by the approved contract sterilizer.",
        (
            "Sterilize only using the validated EO cycle defined in WI-101 at the "
            "approved contract sterilizer.",
            "Include biological indicators and process challenge devices in each "
            "load per the validation.",
            "Review the sterilization batch record, parametric data, and BI "
            "results before load release.",
            "Quarantine the load until Quality Assurance disposition; release "
            "requires all acceptance criteria met.",
            "Requalify the cycle annually and after any change to product, "
            "packaging, or load configuration.",
            "Monitor EO and ECH residuals against ISO 10993-7 limits on each requalification.",
        ),
        ("Sterilization batch records", "BI incubation results", "Requalification reports"),
        ("21 CFR 820.75",),
        ("ISO 11135:2014", "ISO 13485:2016 Clause 7.5.7"),
        (101,),
    ),
    ProcedureSpec(
        13,
        "sop",
        "Training and Competency",
        "Human Resources",
        "Establish identification of training needs and verification of "
        "competency for personnel affecting product quality.",
        "Applies to all Halvern employees and temporary staff performing quality-impacting work.",
        (
            "Define role-based training curricula in the training matrix TRN-100.",
            "Train personnel on new or revised documents before their effective "
            "date; record trainer, trainee, document, and revision.",
            "Verify competency for special processes by observation or "
            "examination before independent work is permitted.",
            "Review training records for completeness during internal audits per SOP-014.",
            "Retrain when audits, nonconformances, or complaints indicate a training gap.",
        ),
        ("Training matrix", "Training records", "Competency assessments"),
        ("21 CFR 820.25",),
        ("ISO 13485:2016 Clause 6.2",),
        (14,),
    ),
    ProcedureSpec(
        14,
        "sop",
        "Internal Audit",
        "Quality Assurance",
        "Establish planning and conduct of internal quality system audits.",
        "Applies to all elements of the Halvern quality management system.",
        (
            "Prepare an annual audit schedule covering all QMS processes at least "
            "once per year, weighted by risk and prior findings.",
            "Use trained auditors independent of the area being audited.",
            "Document findings with objective evidence; classify as major or "
            "minor nonconformity or observation.",
            "Route nonconformities to CAPA per SOP-004; verify correction and "
            "corrective action before closing the finding.",
            "Report audit results to management review per SOP-015.",
        ),
        ("Audit schedule", "Audit reports", "Finding closure evidence"),
        ("21 CFR 820.22",),
        ("ISO 13485:2016 Clause 8.2.4",),
        (4, 15),
    ),
    ProcedureSpec(
        15,
        "sop",
        "Management Review",
        "Executive",
        "Define the conduct of management reviews of the quality management system.",
        "Applies to the Halvern executive team and QMS process owners.",
        (
            "Conduct management review at least twice per year with the required "
            "inputs defined in this procedure.",
            "Review audit results, complaint and MDR trends, CAPA status "
            "including overdue effectiveness checks, supplier performance, and "
            "quality objectives.",
            "Record decisions and actions with owners and due dates.",
            "Track actions to closure and review status at the next meeting.",
        ),
        ("Management review minutes", "Action tracker"),
        ("21 CFR 820.20(c)",),
        ("ISO 13485:2016 Clause 5.6",),
        (14, 4),
    ),
    ProcedureSpec(
        16,
        "sop",
        "Labeling Control",
        "Manufacturing",
        "Define controls for label content, printing, inspection, and application.",
        "Applies to all device, packaging, and shipping labels for Halvern products.",
        (
            "Release label artwork through document control; verify UDI content per SOP-022.",
            "Print labels against a released artwork revision; reconcile label "
            "counts at the end of each run.",
            "Inspect the first article of each label run against the released artwork.",
            "Apply labels per WI-101 at the designated station; verify correct "
            "label at final inspection.",
            "Destroy obsolete and excess labels and record the destruction.",
        ),
        ("Label reconciliation records", "First article inspections"),
        ("21 CFR 820.120",),
        ("ISO 13485:2016 Clause 7.5.1",),
        (22, 101),
    ),
    ProcedureSpec(
        17,
        "sop",
        "Packaging and Shipping",
        "Manufacturing",
        "Define packaging, preservation, and shipping controls for finished devices.",
        "Applies to sterile-barrier and shipping packaging of Halvern devices.",
        (
            "Package devices in the validated sterile barrier system per the "
            "packaging specification.",
            "Seal per validated sealer parameters; record seal strength samples each shift.",
            "Perform final packaging inspection including label verification.",
            "Ship only released product; verify shipping documentation includes lot and UDI.",
            "Requalify packaging annually including transit testing per ISTA 3A.",
        ),
        ("Seal strength logs", "Packaging validation reports", "Shipping records"),
        ("21 CFR 820.130",),
        ("ISO 11607-1:2019", "ISO 13485:2016 Clause 7.5.11"),
        (),
    ),
    ProcedureSpec(
        18,
        "sop",
        "Environmental and Contamination Control",
        "Manufacturing",
        "Define environmental controls for the controlled assembly area.",
        "Applies to the ISO Class 8 assembly room and its support areas.",
        (
            "Maintain the assembly room at ISO 14644-1 Class 8 with positive "
            "pressure to adjacent areas.",
            "Monitor particulates monthly and viable counts quarterly; trend "
            "results against alert and action limits.",
            "Control gowning per the posted gowning procedure; verify training "
            "before unescorted access.",
            "Clean per the cleaning schedule using approved agents.",
            "Investigate excursions beyond action limits and assess product impact per SOP-005.",
        ),
        ("Environmental monitoring data", "Cleaning logs", "Gowning training"),
        ("21 CFR 820.70(c)",),
        ("ISO 13485:2016 Clause 6.4",),
        (5,),
    ),
    ProcedureSpec(
        19,
        "sop",
        "Field Action and Recall",
        "Regulatory Affairs",
        "Define initiation and execution of corrections and removals in the field.",
        "Applies to all Halvern devices in distribution.",
        (
            "Regulatory Affairs initiates a field action by convening the field "
            "action committee when a reported issue may require correction or removal.",
            "Perform a health hazard evaluation using the risk management file per SOP-003.",
            "The Director of Quality Assurance approves the field action "
            "classification and the decision to proceed before any customer "
            "notification is issued.",
            "Classify the action and notify FDA per 21 CFR 806 where required.",
            "Execute customer notifications and product retrieval with "
            "effectiveness checks on notification receipt.",
            "Track returned product and reconcile against distribution records.",
            "Close the action with a final report and evaluate the need for CAPA per SOP-004.",
        ),
        ("Health hazard evaluations", "Field action files", "Effectiveness checks"),
        ("21 CFR 806", "21 CFR 7"),
        ("21 CFR 806", "ISO 13485:2016 Clause 8.3.3"),
        (3, 4),
    ),
    ProcedureSpec(
        20,
        "sop",
        "Statistical Techniques and Sampling",
        "Quality Assurance",
        "Define valid statistical techniques for acceptance activities and process monitoring.",
        "Applies to sampling plans, process capability studies, and trend analyses across the QMS.",
        (
            "Select sampling plans from ANSI/ASQ Z1.4 based on the criticality "
            "classification of the characteristic.",
            "Justify AQL selection in the inspection plan; critical "
            "characteristics require tightened inspection or 100% verification.",
            "Use control charts for validated process parameters; react to "
            "out-of-control signals per the reaction plan.",
            "Document the statistical rationale for verification and validation sample sizes.",
        ),
        ("Sampling plan justifications", "Control charts", "Capability studies"),
        ("21 CFR 820.250",),
        ("ISO 13485:2016 Clause 8.1",),
        (),
    ),
    ProcedureSpec(
        21,
        "sop",
        "Software Lifecycle and Validation",
        "Engineering",
        "Define lifecycle controls for device firmware and validation of "
        "software used in the quality system.",
        "Applies to HALVERN device firmware (IEC 62304 Class C) and to "
        "quality-system software tools.",
        (
            "Classify device software per IEC 62304 and plan lifecycle activities accordingly.",
            "Maintain software requirements traceable to system requirements and risk controls.",
            "Perform static analysis and unit testing on all firmware changes; "
            "maintain anomaly lists with risk evaluation.",
            "Perform software system testing on production-equivalent hardware before release.",
            "Validate quality-system software tools for intended use "
            "proportionate to risk before first use and after changes.",
        ),
        ("Software development plan", "Test reports", "Tool validation records"),
        ("21 CFR 820.30(g)", "21 CFR 820.70(i)"),
        ("IEC 62304:2006+A1", "ISO 13485:2016 Clause 4.1.6"),
        (2,),
    ),
    ProcedureSpec(
        22,
        "sop",
        "Unique Device Identification",
        "Regulatory Affairs",
        "Define assignment and submission of UDI for Halvern devices.",
        "Applies to all finished devices and their packaging levels.",
        (
            "Assign device identifiers through the issuing agency account and "
            "record them in the UDI register.",
            "Include production identifiers (lot, serial, expiration) in the "
            "label per the labeling specification.",
            "Submit and maintain GUDID records; verify submissions after each change.",
            "Verify UDI carrier readability at final inspection per SOP-016.",
        ),
        ("UDI register", "GUDID submission confirmations"),
        ("21 CFR 830", "21 CFR 801.20"),
        ("21 CFR 830", "ISO 13485:2016 Clause 7.5.8"),
        (16,),
    ),
    ProcedureSpec(
        23,
        "sop",
        "Records Retention and Data Integrity",
        "Quality Assurance",
        "Define retention periods and data integrity controls for quality records.",
        "Applies to paper and electronic quality records including eQMS data.",
        (
            "Retain device history records, complaint files, and design history "
            "files for the device lifetime plus two years, minimum five years.",
            "Protect electronic records with access control, audit trails, and "
            "scheduled backups; verify restore annually.",
            "Apply ALCOA+ principles to record creation: attributable, legible, "
            "contemporaneous, original, accurate.",
            "Control record corrections with single-line strikethrough, initials, "
            "and date; electronic corrections retain the original entry.",
            "Archive records at end of active use and index the archive for "
            "retrieval within two business days during inspections.",
        ),
        ("Retention schedule", "Backup and restore logs", "Archive index"),
        ("21 CFR 820.180", "21 CFR 11"),
        ("ISO 13485:2016 Clause 4.2.5", "21 CFR 11"),
        (),
    ),
    ProcedureSpec(
        24,
        "sop",
        "Change Control",
        "Engineering",
        "Define evaluation and implementation of changes to product, process, "
        "and quality system documents.",
        "Applies to all changes affecting device design, manufacturing, suppliers, or the QMS.",
        (
            "Initiate a change order describing the change, reason, and affected "
            "documents and products.",
            "Assess impact on design outputs, risk file, verification and "
            "validation, regulatory filings, and inventory.",
            "Determine regulatory reportability of the change before implementation.",
            "Obtain cross-functional approval; implement through document control per SOP-001.",
            "Verify implementation including training per SOP-013 and first-lot "
            "review where the change affects production.",
        ),
        ("Change orders", "Impact assessments", "Implementation evidence"),
        ("21 CFR 820.30(i)", "21 CFR 820.40"),
        ("ISO 13485:2016 Clause 7.3.9",),
        (1, 13),
    ),
)

WIS: tuple[ProcedureSpec, ...] = (
    ProcedureSpec(
        101,
        "wi",
        "EO Sterilization Cycle and Load Configuration",
        "Manufacturing",
        "Define the validated ethylene oxide cycle parameters and approved load configurations.",
        "Applies to sterilization of HALVERN finished devices at the contract sterilizer.",
        (
            "Configure loads only per the approved load diagrams in this instruction.",
            "Verify preconditioning at 45-55% RH and 30-40 C for a minimum of 12 hours.",
            "Execute the validated cycle: EO concentration 650 mg/L, exposure 4 "
            "hours, temperature 50 C.",
            "Place biological indicators at the qualified worst-case locations "
            "shown in the load diagram.",
            "Aerate for a minimum of 48 hours before residual testing release.",
        ),
        ("Load configuration records", "Cycle printouts"),
        ("21 CFR 820.75",),
        ("ISO 11135:2014",),
        (12,),
    ),
    ProcedureSpec(
        102,
        "wi",
        "Wire Bonding Operation",
        "Manufacturing",
        "Define setup and operation of the wire bonder for hybrid circuit assembly.",
        "Applies to gold wire bonding of the PCB-300 hybrid circuit assembly.",
        (
            "Verify bonder qualification status and parameter recipe against the "
            "process specification before starting.",
            "Perform first-article pull tests each shift; minimum pull strength 8 "
            "gf, record results on the traveler.",
            "Bond per the approved bonding diagram; visually inspect each device "
            "at 30x magnification.",
            "Stop the line and notify engineering if two consecutive pull tests "
            "fail; segregate product per SOP-005.",
        ),
        ("Pull test logs", "Bonder parameter records"),
        ("21 CFR 820.70",),
        ("ISO 13485:2016 Clause 7.5.1",),
        (5,),
    ),
    ProcedureSpec(
        103,
        "wi",
        "Enclosure Laser Welding",
        "Manufacturing",
        "Define laser weld parameters and inspection for the titanium enclosure closure weld.",
        "Applies to seam welding of the HSG-100 enclosure on the HALVERN pump.",
        (
            "Verify laser qualification and the released weld schedule before each lot.",
            "Purge the weld chamber with argon to below 50 ppm oxygen before initiating the weld.",
            "Execute the closure weld per the weld schedule; record actual power "
            "and speed on the traveler.",
            "Inspect welds at 20x for cracks, porosity, and coverage; perform "
            "helium leak test per the acceptance criterion of 1e-9 atm-cc/s.",
            "Route leak test failures to SOP-005; no weld repair is permitted "
            "without engineering disposition.",
        ),
        ("Weld schedule records", "Leak test results"),
        ("21 CFR 820.70",),
        ("ISO 13485:2016 Clause 7.5.1",),
        (5,),
    ),
    ProcedureSpec(
        104,
        "wi",
        "Final Flow and Electrical Test and Device Analysis",
        "Manufacturing",
        "Define final acceptance testing of finished pumps and analysis of returned devices.",
        "Applies to final test of the HALVERN pump family and complaint device analysis.",
        (
            "Run the automated final test sequence covering delivered flow rate, "
            "occlusion detection, telemetry link, and current drain.",
            "Verify battery open-circuit voltage is within specification and "
            "record measured longevity projection.",
            "Program the device to shipment settings and verify with an independent readback.",
            "For returned devices, decontaminate per the biosafety procedure "
            "before analysis and preserve evidence for the complaint file.",
            "Record analysis findings on the complaint investigation form per SOP-006.",
        ),
        ("Final test records", "Device analysis reports"),
        ("21 CFR 820.80(d)",),
        ("ISO 13485:2016 Clause 8.2.4",),
        (6,),
    ),
)

ALL_PROCEDURES: tuple[ProcedureSpec, ...] = SOPS + WIS
