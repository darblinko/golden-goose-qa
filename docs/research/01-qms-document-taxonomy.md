# QMS Document Taxonomy for Audit-Facing RAG / Knowledge Graph

**Scope:** Definitive document taxonomy for a Class III medical device manufacturer's QMS corpus, designed to drive (a) the ingestion pipeline (format handling, chunking strategy, metadata extraction) and (b) the Neo4j knowledge graph schema (entities + edges). Target use case: answering questions live during an FDA inspection or notified body / ISO 13485 audit.

**Date:** 2026-07-17. Regulatory citations verified against eCFR, FDA.gov, and current secondary sources as of this date.

---

## 1. Regulatory Context (verified)

### 1.1 The QMSR transition — critical framing for 2026

- FDA's **Quality Management System Regulation (QMSR) final rule** (published Feb 2, 2024) took effect **February 2, 2026**. 21 CFR Part 820 now **incorporates ISO 13485:2016 by reference** (plus Clause 3 of ISO 9000:2015 for terminology).
- The old QSR's prescriptive sections (820.20–820.198) are gone. What remains in the new Part 820:
  - **§ 820.10 — Requirements for a quality management system.** Incorporates ISO 13485:2016; links in other applicable FDA parts (803 MDR, 806 corrections/removals, 821 tracking, 830/801 UDI) and clarifies applicability of design and development requirements.
  - **§ 820.35 — Control of records.** Additions on top of ISO 13485 4.2.5: complaint and servicing record content (incl. info required by Part 803 and whether the complaint was investigated / MDR-reportable), UDI documentation per Part 830, confidentiality/signature/date requirements.
  - **§ 820.45 — Device labeling and packaging controls.** Retained from the old QSR (old 820.120/820.130) because FDA judged ISO 13485 insufficient here — labeling inspection/examination and release activities remain explicit US requirements.
- Terminology mapping the corpus will straddle (documents written pre-2026 use QSR terms; newer docs use ISO 13485 terms). The RAG system MUST treat these as synonyms:

| Old QSR term (pre-Feb-2026 docs) | Old cite | QMSR / ISO 13485:2016 equivalent | New cite |
|---|---|---|---|
| Design History File (DHF) | 820.30(j) | Design and development file | ISO 13485 § 7.3.10 |
| Device Master Record (DMR) | 820.181 | Medical Device File | ISO 13485 § 4.2.3 |
| Device History Record (DHR) | 820.184 | Production/batch records (record of each batch/unit) | ISO 13485 § 7.5.1, 7.5.9, 4.2.5 |
| Management with executive responsibility | 820.20 | Top management; management review | ISO 13485 § 5.1, 5.6 |
| Quality audit | 820.22 | Internal audit | ISO 13485 § 8.2.4 |
| Personnel/training | 820.25 | Human resources / competence | ISO 13485 § 6.2 |
| Design controls | 820.30 | Design and development | ISO 13485 § 7.3.1–7.3.10 |
| Document controls | 820.40 | Control of documents | ISO 13485 § 4.2.4 |
| Purchasing controls | 820.50 | Purchasing / supplier evaluation | ISO 13485 § 7.4.1–7.4.3 |
| Nonconforming product | 820.90 | Control of nonconforming product | ISO 13485 § 8.3 |
| CAPA | 820.100 | Corrective action; Preventive action (split) | ISO 13485 § 8.5.2, 8.5.3 |
| Inspection, measuring, test equipment | 820.72 | Control of monitoring and measuring equipment | ISO 13485 § 7.6 |
| Process validation | 820.75 | Validation of processes for production | ISO 13485 § 7.5.6 |
| Acceptance activities | 820.80/820.86 | Monitoring/measurement of product; identification of status | ISO 13485 § 8.2.6, 7.5.8 |
| Complaint files | 820.198 | Complaint handling (+ § 820.35 additions) | ISO 13485 § 8.2.2; 21 CFR 820.35 |
| Servicing | 820.200 | Servicing activities (+ § 820.35) | ISO 13485 § 7.5.4 |
| Statistical techniques | 820.250 | Analysis of data | ISO 13485 § 8.4 |

### 1.2 Other verified regulatory anchors

| Regime | Key cites (verified) | Governs |
|---|---|---|
| 21 CFR Part 803 | 803.17 (MDR procedures), 803.18 (MDR event files), 803.50/803.52 (manufacturer 30-day reports, content), 803.53 (5-day reports), 803.56 (supplemental reports); eMDR final rule (2014) mandates electronic Form FDA 3500A | Adverse event / MDR reporting |
| 21 CFR Part 806 | 806.10 (reports of corrections and removals), 806.20 (records of non-reportable corrections/removals) | Recalls, corrections, removals |
| 21 CFR Part 812 | 812.20 (IDE application), 812.25 (investigational plan), 812.140 (sponsor + investigator records), 812.150 (reports; UADE in 10 working days; annual progress reports) | Investigational device studies |
| 21 CFR Part 814 | 814.20 (PMA content), 814.39 (PMA supplements: panel-track, 180-day, real-time, 30-day notice), 814.84 (postapproval periodic/annual reports) | Premarket approval (Class III) |
| 21 CFR Part 821 | Device tracking (OAFR under new inspection program) | Tracked implants/life-sustaining devices |
| 21 CFR Parts 801/830 | UDI labeling and GUDID | UDI |
| ISO 14971:2019 | 4.4 risk management plan; 4.5 risk management file; Cl. 5 risk analysis (5.2 intended use, 5.4 hazard identification, 5.5 risk estimation); Cl. 6 risk evaluation; Cl. 7 risk control; Cl. 8 overall residual risk / benefit-risk; Cl. 9 risk management review → risk management report; Cl. 10 production & post-production | Risk management |
| IEC 62366-1:2015+A1 | Usability engineering file; use-related risk analysis; formative/summative evaluation | Usability |
| IEC 60601-1 (+collaterals/particulars) | Basic safety & essential performance; CB scheme test reports | Electrical medical devices |
| IEC 62304:2006+A1:2015 | Safety classes A/B/C; 5.1–5.8 development process; Cl. 6 maintenance; Cl. 7 software risk; Cl. 8 configuration mgmt (SOUP in 8.1.2); Cl. 9 problem resolution | Device software lifecycle |
| Sterilization standards | ISO 11135 (EO), ISO 11137-1/-2 (radiation, VDmax dose audits), ISO 17665 (moist heat), ISO 10993-7 (EO residuals), ISO 11737 (bioburden/sterility) | Sterilization validation |
| Biocompatibility | ISO 10993-1 (evaluation framework) + part-specific (-3, -4, -5, -6, -10, -11, -17, -18, -23); FDA 10993-1 guidance | Biological evaluation |

### 1.3 Inspection frameworks (drives query patterns — detail in § 6)

- **QSIT** (Quality System Inspection Technique, 1999 guide; CP 7382.845): top-down inspection of **four subsystems — Management Controls, Design Controls, CAPA, Production & Process Controls (P&PC)** — with three satellites (sterilization process controls, MDR, corrections & removals) and binomial-based **sampling tables**. The bulk of the legacy corpus and most auditors' mental models were shaped by QSIT.
- **As of Feb 2, 2026 QSIT is retired.** FDA now inspects under **Compliance Program 7382.850**, organized around **six QMS Areas** (Management Responsibility; Resource Management; Product Realization; Measurement, Analysis & Improvement; Outsourcing & Purchasing; Change Control) and **four OAFRs** (MDR — Part 803; Corrections & Removals — Part 806; Tracking — Part 821; UDI — Parts 801/830). Inspections are risk-based; investigators reportedly use the manufacturer's **risk management file as the roadmap** and trace threads across functions (complaint → investigation → CAPA → design change → risk file → management review). Secondary sources report internal audit and supplier audit *reports* are no longer categorically off-limits as they effectively were under the QSR-era policy — treat as reported change and verify against the CP text before relying on it.
- **ISO 13485 certification audits** (notified body / registrar, incl. MDSAP): Stage 1 (documentation readiness), Stage 2 (implementation), annual surveillance, 3-year recertification; process-based auditing following the process map, with mandatory coverage of design, CAPA, complaints, and regulatory reporting each cycle (MDSAP audit model with per-process tasks and country-specific modules).

---

## 2. Structural Typology of QMS Documents

Every family in § 3 belongs to one or more of these structural classes. The ingestion pipeline should branch on structural class first, family second.

| Structural class | Description | Chunking/parsing implications | Families |
|---|---|---|---|
| **A. Narrative controlled document** | Word→PDF, numbered sections (1.0 Purpose, 2.0 Scope, 3.0 References, 4.0 Definitions, 5.0 Procedure...), header/footer block with doc#/rev/page, revision history table, approval/signature block | Chunk on numbered headings; extract header/footer metadata once, strip repeats; revision-history and reference tables → structured extraction, not prose chunks | Quality manual, SOPs, WIs, plans (design/risk/software/validation plans), reports (design review minutes, validation reports, CERs, audit reports, mgmt review minutes) |
| **B. Matrix / tabular (Excel-native)** | Wide spreadsheets: one row = one requirement/failure mode/hazard/asset; many ID-bearing columns | Row-level chunking (1 row = 1 chunk or small row-groups) with column headers repeated in every chunk; column values are graph edges — extract to structured store, don't just embed | Trace matrices, DFMEA/PFMEA, control plans, hazard analysis worksheets, ASL, equipment/calibration masters, complaint/CAPA/NCR logs, SOUP lists |
| **C. Structured form (record instance)** | A controlled form template (FRM-xxx) filled per event: labeled fields + free-text narrative sections + disposition/approval signatures | Field extraction (key-value) + narrative sections as chunks; the record ID is the graph node key; forms are the highest-density source of cross-reference IDs | CAPA, NCR, deviation, complaint, SCAR, MDR 3500A, ECO/DCO, design review action items, audit findings |
| **D. Production/logbook record** | DHR travelers, batch records, equipment logs: step-by-step tables, initials/date at each step, attached printouts (test data, environmental monitoring) | Page/step-level parsing; heavy OCR need; extract lot/serial/PN/equipment/operator IDs; often mixed machine print + handwriting | DHRs, sterilization load records, calibration certs, maintenance logs, training sign-off sheets |
| **E. Scanned / wet-signature legacy** | Older records scanned to image-PDF (no text layer), faxed supplier certs, signed approval pages appended to digital docs | OCR pipeline mandatory (incl. handwriting for initials/dates); signature block detection; confidence scoring; flag low-confidence extractions for human review during audit prep | Any pre-eQMS record; signature pages of otherwise-digital docs; supplier CoCs/CoAs |
| **F. Engineering/CAD output** | Drawings (PDF prints of CAD w/ title block), specs, BOMs (Excel/ERP export), schematics | Title-block extraction (drawing #, rev, PN, material, tolerance block); BOM rows → graph edges (assembly→component); drawing body is low-value for text RAG but title block + notes are high-value | Design outputs, DMR content |
| **G. Regulated e-format** | eMDR HL7 ICSR XML (3500A electronic equivalent), eCopy/eSTAR submission structures, GUDID records | Native structured parse (XML/JSON) — never OCR; map fields directly to graph properties | eMDR submissions, PMA eCopy, UDI/GUDID |

Cross-cutting parsing assets worth building once: (1) header/footer metadata block detector (doc #, rev, effective date, page x of y, "CONFIDENTIAL — uncontrolled when printed"); (2) revision-history table parser (Rev | Date | Description | Author/ECO#); (3) signature-block parser (name/title/date, digital-signature manifests from eQMS exports, e.g. MasterControl/Veeva/Greenlight "signature manifest" trailing pages); (4) doc-ID regex bank (§ 5).

---

## 3. Document Family Catalog

Template per family: **(1)** purpose & regulatory basis, **(2)** formats, **(3)** internal structure to exploit for chunking, **(4)** key metadata, **(5)** cross-references (graph edges), **(6)** typical volume, **(7)** auditor focus.

### 3.1 Quality Manual, SOPs, and Work Instructions

1. **Purpose/basis:** The procedural backbone. Quality manual per ISO 13485 § 4.2.2 (scope, exclusions/non-applications, process interactions); documented procedures per § 4.2.4 (control of documents) and per-process clauses (each "shall document a procedure" in 13485 spawns an SOP). Pre-2026 basis: 21 CFR 820.40, 820.186 (quality system record). Work instructions (WIs) are level-3 detail under SOPs; forms (level 4) are the templates records get written on.
2. **Formats:** Structural class A. Word-authored, PDF-published from eQMS; flowcharts embedded (Visio); forms as Word/Excel attachments or separate FRM- docs. Legacy revisions may be scans with wet signatures.
3. **Chunking:** Fixed numbered-section skeleton (Purpose / Scope / References / Definitions / Responsibilities / Procedure steps / Records / Appendices). Chunk at heading level 2 (x.y). The **References section** and **revision history table** should be extracted structurally, not embedded as prose. Procedure step numbering (5.1, 5.1.1) supports fine-grained citation — auditors ask "show me where your procedure requires X"; answers must cite section numbers. Header/footer on every page repeats doc#/rev — dedupe.
4. **Metadata:** doc number (SOP-xxx / QP-xxx / WI-xxx), revision, title, effective date, next review date, owner (role + department), approvers, status (Draft/In Review/Effective/Obsolete), process area (map to ISO 13485 clause), superseded revision, associated forms.
5. **Cross-refs:** SOP → parent quality manual section; SOP → other SOPs ("per SOP-002"); SOP → forms it spawns (FRM-xxx); SOP → regulatory clauses it implements (820.x / 13485 §, often in a compliance matrix appendix); SOP → WIs; SOP revision → ECO/DCO that changed it; SOP → training curricula (who must train on it). Every record instance in the QMS points back to the SOP revision in force when it was created.
6. **Volume:** Mid-size Class III firm: quality manual (1, 20–60 pp); 60–300 SOPs (5–25 pp each); 100–600 WIs (2–15 pp); 150–500 forms. Total ≈ 500–1,500 controlled docs, 5,000–20,000 pages, plus obsolete revision history (multiply ×3–10 revisions each).
7. **Auditor focus:** "Show me your procedure for [CAPA/complaints/design change]." Is the SOP's current rev the one people trained on? Does practice match procedure (they read the SOP then sample records against it)? Obsolete-document control (can an old rev be found at a workstation?). Review cadence. Under CP 7382.850, whether procedures reference ISO 13485 clauses correctly post-QMSR.

### 3.2 Design History File (DHF) / Design and Development File

Umbrella per old 820.30(j), now ISO 13485 § 7.3.10 ("design and development file" per device/family). The DHF is an *index* over the components below — often literally a DHF index spreadsheet listing every constituent doc with number/rev/location. That index is a first-class graph asset: ingest it as edges, not text.

#### 3.2.1 Design and Development Plan
1. 820.30(b) / 13485 § 7.3.2. Defines stages, deliverables per stage, review gates, responsibilities, interfaces; updated as design evolves.
2. Class A narrative + Gantt/deliverable tables.
3. Chunk by phase; the **deliverables table** (deliverable → doc # → phase → responsible role) is a graph feed.
4. Plan #, rev, project/product name, phase gates, dates.
5. → every planned DHF deliverable; → risk management plan; → software development plan; → applicable SOP (design control SOP).
6. 1–3 per project, 10–40 pp, revised 3–8 times over a program.
7. "Did you follow your own plan?" Auditors reconcile plan deliverables vs. actual DHF contents and check the plan was updated, not abandoned.

#### 3.2.2 Design Inputs (requirements)
1. 820.30(c) / 13485 § 7.3.3. User needs, intended use, performance, safety, regulatory, and standards requirements; must be unambiguous, non-conflicting, verifiable. For Class III, ties directly to PMA claims.
2. Requirements spec documents (Word/PDF, class A) *and* requirements-management exports (Excel/CSV from Jama/DOORS/Polarion — class B). Often split: User Needs (UN), System/Product Requirements (PRD/SRS), subsystem requirements.
3. One requirement = one atomic unit with its own ID (e.g., PRD-123, REQ-0456). Chunk per requirement or small clusters; keep requirement ID, text, rationale, source, and acceptance criteria together.
4. Requirement ID, parent doc # + rev, category (performance/safety/usability/regulatory), source (user need ID, standard clause, risk control), verification method (T/I/A/D — test/inspection/analysis/demonstration).
5. **Densest node type in the graph:** requirement → parent user need; → verifying protocol/test ID; → design output/spec that satisfies it; → risk control it implements (risk file ID); → standard clause (IEC 60601-1 § x) it embodies; → labeling claims. The trace matrix (§ 3.3) materializes these.
6. 1–10 requirement docs per product; 200–5,000 individual requirements for a complex Class III electromechanical device.
7. QSIT Design Controls objective: pick a requirement, demand the full thread — input → output → verification → validation → risk. Also: were inputs reviewed/approved before verification started? How were conflicts resolved?

#### 3.2.3 Design Outputs
1. 820.30(d) / 13485 § 7.3.4. The specifications that define the device: drawings, specs, BOMs, source code, labeling masters, acceptance criteria. Must be traceable to inputs and identify outputs essential to proper functioning (a formal "essential design outputs" list — auditors ask for it).
2. Class F (CAD prints w/ title blocks, BOM exports) + class A (spec documents) + code repos.
3. Title-block extraction (drawing #, rev, PN, sheet x of y, material/finish notes, tolerance block); BOM rows = assembly→component edges with quantities; spec docs chunk by section.
4. Drawing/spec/PN number, rev, description, material, supplier (if bought), where-used.
5. Output → input(s) satisfied; output → DMR/MDF (outputs *are* most of the DMR); PN → BOM parent/child; drawing → ECOs that revised it; essential outputs list → DHR acceptance steps that verify them in production.
6. Hundreds to thousands of drawings/specs per device; BOMs 50–2,000 lines.
7. "Show me the essential design outputs and how production verifies them." Rev consistency between DHF, DMR, and shop floor.

#### 3.2.4 Design Reviews
1. 820.30(e) / 13485 § 7.3.5. Documented, systematic reviews at planned stages; participants must include an independent reviewer (old QSR) / representatives of functions concerned.
2. Class A/C hybrid: agenda + minutes + action item table + attendance/signature sheet (often scanned, class E).
3. Chunk: decision summary; open action items table (structured extraction — IDs, owners, due dates, closure evidence); attendance block (people nodes).
4. Review ID/meeting #, phase gate, date, product/project, attendees + roles, outcome (pass/conditional/fail).
5. Review → DHF phase; → documents reviewed (input/output doc IDs + revs); → action items → their closure records; → design plan gate it satisfies.
6. 3–10 per project, 5–30 pp each incl. attachments.
7. "Show design review for phase X — who attended, was the independent reviewer present, were all actions closed before proceeding?"

#### 3.2.5 Design Verification (protocols + reports)
1. 820.30(f) / 13485 § 7.3.6: outputs meet inputs. Includes bench testing, IEC 60601-1 electrical safety/EMC (60601-1-2) reports from test houses (CB scheme reports, TRF format), package integrity (ISO 11607, ASTM F88/F2096), shelf-life/accelerated aging (ASTM F1980).
2. Protocols: class A with test-case tables. Reports: class A + raw-data appendices (instrument printouts, class D/E), stats tables, sometimes 60601 CB reports = 200–800 pp semi-structured test-clause tables keyed to standard clauses.
3. Protocol: chunk per test case (test ID, requirement(s) verified, method, sample size + justification, acceptance criteria). Report: results-summary table (test case → pass/fail → data location) is the key structure; deviations-from-protocol section is high audit value. CB reports: chunk per standard clause (clause # column present throughout).
4. Protocol/report # + rev (often paired: VER-xxx-P / VER-xxx-R or TP-xxx/TR-xxx), product + rev tested, test article lots/serials, equipment used (asset IDs), test dates, personnel, pass/fail.
5. Protocol → requirements verified (trace matrix rows); report → protocol; report → test-article DHR/lot; report → equipment/calibration records (asset IDs at time of test); report → protocol deviations (deviation IDs); report → NCRs for failures; failures → design changes (ECO) or requirement changes.
6. 20–200 protocol/report pairs per program; reports 10–100 pp each (60601/EMC reports far larger). Total verification evidence commonly 5,000–50,000 pp for a Class III device.
7. Sample-size justification (statistical rationale), acceptance criteria pre-defined (not retro-fitted), failures handled via NCR/deviation not quietly re-run, equipment calibrated at test time, protocol approved *before* execution (date arithmetic — auditors check signature dates).

#### 3.2.6 Design Validation (protocols + reports)
1. 820.30(g) / 13485 § 7.3.7: device meets user needs and intended use, under actual/simulated use, on initial production units or equivalents; includes software validation and clinical evaluation. Human factors summative evaluation (IEC 62366-1) is usually filed here or in the usability file.
2. Same as verification, plus HF summative reports (video/observation data references) and clinical evidence (see § 3.15).
3. As 3.2.5; plus rationale for production-equivalence of test units — a named section auditors request.
4. As 3.2.5 + user-need IDs validated, use environment, participant demographics (HF).
5. Validation → user needs; → summative usability report → use-related risk analysis (URRA) tasks; → clinical evaluation report; → production-equivalent DHR/lots used.
6. 3–20 protocol/report pairs; HF summative report 30–150 pp.
7. "Validation used production units or equivalents — show the equivalence rationale." Coverage of all user needs and use environments; link from use errors found → risk file updates.

#### 3.2.7 Design Transfer
1. 820.30(h) / 13485 § 7.3.8. Design correctly translated into production specifications. Evidence: transfer plan/checklist, process validation (IQ/OQ/PQ) linkage, first-article inspection, pilot builds, DMR completeness check.
2. Class A checklist + matrix; FAI reports (AS9102-style tables in some firms).
3. Transfer checklist rows (deliverable → status → evidence doc #) = graph edges.
4. Transfer plan/report #, product, effectivity date/lot ("as of lot X built to DMR rev Y").
5. Transfer → DMR sections verified complete; → process validations (VAL-xxx); → pilot DHRs; → training records for production staff; → released BOM/routing revs.
6. 1 plan + 1 report per product/line; 10–50 pp + referenced evidence.
7. "How do you know production builds what design released?" Pilot-lot disposition, process validation completion *before* commercial distribution.

#### 3.2.8 Design Changes
1. 820.30(i) / 13485 § 7.3.9. Post-baseline changes identified, reviewed, verified/validated as appropriate, approved before implementation — flows through the ECO/ECN/DCO system (see § 3.24 change control) with regulatory impact assessment (does this need a PMA supplement per 814.39? a 30-day notice? report in annual report per 814.84?).
2. Class C form (ECO form) + attached redlines, updated docs, V&V evidence.
3. Form field extraction: change description, reason, affected docs table (doc # old rev → new rev), impact assessments (risk, regulatory, validation), disposition of inventory (use-as-is/rework/scrap), effectivity.
4. ECO #, date, originator, affected doc/PN list with rev bumps, regulatory decision (letter-to-file vs supplement), approvals.
5. **Hub node:** ECO → documents/PNs revised (with old/new rev); → CAPA that triggered it; → complaint/NCR root cause; → risk file re-assessment; → new verification protocols/reports; → PMA supplement or annual report line item; → training re-execution; → supplier notifications.
6. 50–500 ECOs/year at a mid-size firm; forms 3–10 pp + attachments.
7. Top audit thread: "list all design changes since the last inspection" → sample → verify V&V of the change, risk re-evaluation, and regulatory reporting decision documentation. Unreported changes needing supplements = major finding territory.

### 3.3 Traceability Matrices
1. **Purpose/basis:** Demonstrate the input→output→V&V thread (820.30 / 13485 § 7.3; explicitly demanded by ISO 14971 § 4.5 for hazard traceability and IEC 62304 § 5.1.1(c)/7.3 for software). Types: requirements trace matrix (UN↔PRD↔SRS↔tests), risk trace matrix (hazard↔control↔verification), software trace (req↔architecture↔unit↔test), standards compliance checklists (60601 clause↔evidence), regulatory compliance matrix (13485 clause↔SOP).
2. **Formats:** Class B — Excel almost universally; sometimes ALM-tool exports (Jama/Polarion) to PDF for signature (a PDF of a 400-column-inch table: parse the Excel source, not the PDF, when both exist).
3. **Chunking:** DO NOT embed as flowing text. One row = one trace link set. Ingest as **edges first**, embeddings second (a per-row synthetic sentence "REQ-123 [text] is verified by TP-045 §6.2 and implements RC-017" embeds well).
4. **Metadata:** matrix doc # + rev, product + baseline rev it applies to, column schema, date/approvals.
5. **Cross-refs:** The matrix *is* cross-references — it is the single highest-value ingest for the knowledge graph. Every cell containing an ID (UN/REQ/SRS/HAZ/RC/TC/TP/TR) is an edge. Also references its source docs (requirement doc revs, protocol revs).
6. **Volume:** 1–10 matrices per product; 200–5,000 rows each.
7. **Auditor focus:** Auditors literally run their inspection off this document: pick a row, pull every referenced artifact, check revs match. Gaps (requirement with no verification; hazard with no control; control with no verification) are findings. Also: is the matrix itself controlled/current with the latest ECO baseline?

### 3.4 DFMEA / PFMEA / Control Plans
1. **Purpose/basis:** Bottom-up failure mode analysis feeding ISO 14971 risk files (14971 Annex B lists FMEA as a technique; AIAG/VDA or IEC 60812 methodology). DFMEA = design failure modes; PFMEA = process failure modes (basis also 13485 § 7.5.6 validation rationale, 820.75 legacy); Control plan = the PFMEA's mitigations operationalized (characteristic → spec → measurement method → sample size → frequency → reaction plan), feeding inspection steps in the DMR/DHR.
2. **Formats:** Class B — wide Excel worksheets (item/function, failure mode, effects, S, cause, O, controls, D, RPN/AP, recommended actions, action results with re-scored S/O/D). Control plans similar. Signed PDF snapshots at rev release.
3. **Chunking:** One row (one failure mode) = one unit; keep S/O/D + actions with the row. Header rows (product, process step, team, rev, date, core team list) = metadata block. Multi-row merged cells (one function → many failure modes) need unmerge logic during parse.
4. **Metadata:** FMEA #, type (D/P), rev, product/process, process step #s (PFMEA links to routing operations), team members, RPN/AP thresholds per SOP, date of last review.
5. **Cross-refs:** DFMEA line → design input/requirement IDs; → risk file hazard/hazardous situation IDs (many firms put an "RMF ref" column); → verification tests that address the failure mode; → design outputs (drawing/PN). PFMEA line → routing operation #; → control plan line; → equipment; → WIs; → historical NCR/complaint IDs cited as occurrence evidence; actions → ECOs/CAPAs. Control plan line → inspection step in DHR traveler; → gauge/asset IDs; → specification (drawing dimension callouts).
6. **Volume:** 1 DFMEA per subsystem (3–15 per product, 100–1,000 rows each); 1 PFMEA per process line; control plans per assembly line. Living documents: expect 5–20 revs.
7. **Auditor focus:** Are FMEAs alive (updated after complaints/NCRs — auditors cross-check "you had 40 complaints for failure X; is its occurrence score still 2?"). Do high-RPN items have completed actions? Does the control plan match actual shop-floor inspection? PFMEA↔process validation coverage.

### 3.5 Risk Management File (ISO 14971:2019)
1. **Purpose/basis:** ISO 14971 § 4.5 — the RMF must provide traceability for **each identified hazard** → risk analysis → evaluation → control implementation & verification → residual risk. Components: **risk management plan** (§ 4.4: scope, responsibilities, criteria for acceptability, verification & post-production activities), **risk analysis** (Cl. 5: intended use + reasonably foreseeable misuse 5.2, characteristics affecting safety 5.3, hazard identification 5.4, risk estimation 5.5 — typically a hazard analysis worksheet plus FMEAs as inputs), **risk evaluation** (Cl. 6), **risk controls** (Cl. 7, incl. 7.4 benefit-risk for individual risks where required, 7.5 new-hazard check, 7.6 completeness), **overall residual risk evaluation / benefit-risk** (Cl. 8), **risk management review + report** (Cl. 9 — pre-commercial review that the plan was executed; the report is the signed conclusion), **production & post-production surveillance** (Cl. 10 — feedback loop from complaints/MDRs/literature back into the file). The QMSR-era FDA inspection uses this file as its roadmap.
2. **Formats:** Plan/report: class A narrative. Hazard analysis: class B matrix (hazard → hazardous situation → sequence of events → harm → severity → P1/P2/probability → risk level → controls → residual). Benefit-risk: narrative w/ clinical citations.
3. **Chunking:** Hazard analysis row-level like FMEA. Plan chunks by clause-mapped sections. Report: conclusions + open-item table. Keep the acceptability criteria matrix (severity × probability grid) as an extractable object — nearly every risk question needs it.
4. **Metadata:** RMF index #, per-doc #s + revs, product/family, risk criteria version, dates of periodic review (Cl. 10 obligates ongoing review — extract the review cadence and last-review date).
5. **Cross-refs:** Hazard ID → harm, severity; → risk controls (RC-xxx) → implementing design outputs (PN/drawing/spec) or protective measures or information for safety (labeling/IFU section refs!); RC → verification-of-implementation evidence (test report IDs) AND verification-of-effectiveness; hazard row → originating FMEA line items, complaints, MDR reports, literature; benefit-risk → CER/clinical data; report → plan rev executed; post-production reviews → complaint trend reports, PMS data, CAPA IDs. Also ↔ usability: URRA task/use-error IDs.
6. **Volume:** Per product family: plan 10–30 pp; hazard analysis 100–2,000 rows; report 10–50 pp; total file (with FMEAs by reference) 500–5,000 pp equivalent. Reviewed/re-issued 1–2×/yr for an active Class III device.
7. **Auditor focus (now the inspection's spine):** "Show me your risk acceptability criteria and who approved them." "Pick hazard H: show every control and its verification." "Show how complaint/MDR data re-entered the file (Cl. 10)." "Overall residual risk vs. benefit — where's the signed conclusion?" Mismatch between risk file probability estimates and actual field data is a classic finding.

### 3.6 Usability Engineering File (IEC 62366-1)
1. Use-related safety per IEC 62366-1: use specification, user interface specification, use-related risk analysis (URRA: tasks → use errors → hazardous situations), formative evaluations, **summative evaluation** protocol/report, UE plan and UE report. FDA HF guidance (2016) drives structure of US submissions ("HF/usability engineering report" in PMA).
2. Class A narratives + class B task/use-error tables + video/session data references.
3. URRA rows like FMEA; summative report chunks per task + per use-error root-cause narrative.
4. UEF doc #s, product + UI rev tested, participant counts per user group.
5. URRA task/use-error IDs → risk file hazardous situations; critical tasks → summative test tasks → results; UI spec → design outputs (labeling, GUI screens); residual use errors → IFU cautions (section refs).
6. 5–15 docs, 200–800 pp total.
7. Were all critical tasks identified via risk analysis and tested summatively? Did field use errors (complaints) trigger UEF updates?

### 3.7 Device Master Record (DMR) / Medical Device File
1. **Purpose/basis:** Old 820.181; now Medical Device File per ISO 13485 § 4.2.3 (for each device family: general description + intended use, labeling, specs for product/production/packaging, monitoring & measurement/acceptance procedures, installation and servicing procedures as applicable). Practically: the *recipe* — device/component specs, drawings, BOM, production process specs (routings, WIs, equipment setup), QA procedures + acceptance criteria, packaging/labeling specs, install/service procedures.
2. **Formats:** Almost always an **index document** (class A/B — a table listing every constituent doc # + rev) over class F engineering docs and class A procedures. In ERP/PLM firms the "DMR" is a released-item baseline (Agile/Windchill/Arena export).
3. **Chunking:** Ingest the index as pure edges (DMR rev → constituent doc # + rev). Constituents are already ingested under their own families — do not double-ingest; link.
4. **Metadata:** DMR/MDF #, rev/baseline date, product + model/catalog numbers, UDI-DI mapping.
5. **Cross-refs:** DMR → every drawing/spec/BOM/routing/WI/label/packaging spec + revs; DMR rev → ECOs between baselines; DMR → DHR template (traveler form rev); DMR ↔ DHF (outputs graduate into DMR at transfer); DMR → device listing/GUDID records.
6. **Volume:** 1 index per device family (5–50 pp) over 200–3,000 constituent docs.
7. **Auditor focus:** Rev integrity: does the DHR of a sampled lot point to the DMR revs actually effective on the build date? Is there any spec on the floor not in the DMR?

### 3.8 Device History Records (DHR) / Batch & Production Records
1. **Purpose/basis:** Old 820.184; now batch/unit records per ISO 13485 § 7.5.1/7.5.9 + § 820.35. Demonstrate each unit/lot was manufactured per the DMR: dates, quantities manufactured/released, acceptance records, primary label + labeling used, UDI/lot/serial numbers.
2. **Formats:** Class D travelers: step-table with operator initials/date per operation; in-process and final inspection data sheets; attached printouts (test station CSVs, torque logs, environmental monitoring); label reconciliation sheets (count issued/used/destroyed — an explicit § 820.45-era control); scanned wet-ink for older lots; eDHR (MES exports) for newer.
3. **Chunking:** Per-operation parsing; extract every ID (lot, serial, PN + rev per BOM issue, equipment asset #s, operator IDs, WI # + rev per step, NCR #s raised mid-build). Handwriting OCR + confidence flags. The final release/disposition signature block (who released, date, quantity) is the most-queried element.
4. **Metadata:** DHR/lot #, product + catalog #, build qty, start/complete dates, DMR baseline rev, released-by + date, serial range, expiry/sterilization lot linkage.
5. **Cross-refs:** DHR → DMR rev; → component lots consumed (supplier lot → receiving inspection records); → equipment used → calibration status; → operators → training records; → in-process NCRs; → sterilization load #; → final release; complaints/MDRs later reference the DHR via lot/serial; recalls scope via DHR lot genealogy. **Lot genealogy (supplier lot → subassembly lot → finished lot → shipped consignee) is the recall-critical subgraph.**
6. **Volume:** Highest-volume family: hundreds to tens of thousands of DHRs/year; 10–200 pp each. Plan for millions of pages; prioritize metadata/ID extraction over full-text embedding.
7. **Auditor focus:** Sampled constantly (P&PC subsystem / Product Realization area): completeness, second-person verification steps, label reconciliation, out-of-spec results handled via NCR, release by authorized person, traceability demo ("for serial S, show me everything").

### 3.9 Nonconformance Reports (NCR / NCMR)
1. **Purpose/basis:** Old 820.90; ISO 13485 § 8.3 (control of nonconforming product: identification, documentation, evaluation, segregation, disposition; 8.3.2 before delivery, 8.3.3 after delivery, 8.3.4 rework).
2. **Formats:** Class C form: description, containment, disposition (use-as-is / rework / repair / scrap / return-to-vendor), justification (esp. UAI — needs engineering rationale + sometimes risk assessment), approvals; plus an NCR log (class B).
3. **Chunking:** Field extraction + narrative sections (description, investigation, disposition rationale). Log ingested as row index.
4. **Metadata:** NCR #, date, source (incoming/in-process/final/field), PN + rev, lot/serial, qty affected, defect code, disposition, supplier (if incoming), closure date, MRB members.
5. **Cross-refs:** NCR → PN/lot/DHR; → supplier (→ SCAR if supplier-caused); → WI/SOP step where detected; → disposition rework WI; → CAPA (if trended/escalated — the NCR→CAPA escalation rationale is audit-critical); → risk file (UAI justifications should cite risk assessment); → complaint (field nonconformances); defect code → trend reports.
6. **Volume:** 200–3,000/yr; 2–8 pp each + log.
7. **Auditor focus:** Escalation logic: "You had 60 NCRs for defect D — why no CAPA?" UAI dispositions with weak rationale. Rework re-inspection to original criteria. Timeliness/aging.

### 3.10 CAPA Records
1. **Purpose/basis:** Old 820.100; ISO 13485 § 8.5.2 (corrective) / 8.5.3 (preventive). The QSIT-era #1 most-cited system; still a core sampling target under CP 7382.850 (Measurement, Analysis & Improvement area).
2. **Formats:** Class C form/eQMS workflow record with phase sections: initiation/source, containment/correction, root cause investigation (5-why/fishbone/Ishikawa attachments), action plan, implementation evidence, **effectiveness check** (criteria + follow-up data), closure; plus CAPA log.
3. **Chunking:** Phase-level chunks; keep root-cause narrative intact; extract the effectiveness-check criteria + result as a structured pair (top auditor question).
4. **Metadata:** CAPA #, open date, source type (complaint/NCR/audit/MDR/trend/supplier), risk priority, owner, phase/status, due/closure dates, extension approvals.
5. **Cross-refs (hub node):** CAPA → source records (complaint IDs, NCR IDs, audit finding IDs, MDR IDs, deviation IDs, SCAR IDs); → root cause → affected SOPs/WIs/specs; → implementing ECOs / SOP revisions / training records (retraining evidence); → effectiveness-check data (post-implementation complaint/NCR rates, follow-up audit); → risk file update; → management review where trended. This is the densest hub in the entire graph.
6. **Volume:** 20–150/yr; 10–60 pp each with attachments.
7. **Auditor focus:** Every inspection samples CAPAs. Statistical basis for trending; root cause depth (not "operator error" every time); actions address root cause; effectiveness objectively verified; timeliness; sources feeding CAPA are comprehensive (all data streams in 820.100(a)(1)-era list / 13485 8.4).

### 3.11 Deviations / Planned Deviations
1. **Purpose/basis:** Temporary, bounded departures from a procedure/spec (planned deviation approved *before* the event; unplanned deviation documented after). Basis: document control + nonconforming-product clauses (13485 § 4.2.4, 8.3); in some QMSs merged into the NCR system. Also protocol deviations during V&V and clinical protocol deviations (21 CFR 812.140(a)(4) requires investigator documentation of protocol deviations).
2. **Formats:** Class C form: scope, duration/lot bounds, justification, risk assessment, approvals; log.
3. **Chunking:** Field extraction; justification + risk-assessment narratives as chunks.
4. **Metadata:** DEV #, type (planned/unplanned/protocol), affected doc # + rev, lots/date window, expiry, approvals.
5. **Cross-refs:** Deviation → SOP/WI/spec deviated from; → lots/DHRs built under it; → risk assessment; → NCR (if product impact) or CAPA (if systemic); protocol deviations → protocol # → report section discussing impact; clinical deviations → site/investigator → IRB notification.
6. **Volume:** 20–200/yr; 2–6 pp.
7. **Auditor focus:** Deviations as permanent-change smell ("this deviation renewed 6 times — why wasn't the spec changed?"); pre-approval dates for planned deviations; V&V report deviations dispositioned with impact analysis.

### 3.12 Supplier Quality (ASL, supplier audits, SCARs, quality agreements)
1. **Purpose/basis:** Old 820.50; ISO 13485 § 7.4.1 (evaluation/selection criteria proportionate to risk, re-evaluation, records), 7.4.2 (purchasing information incl. notification-of-change agreements), 7.4.3 (verification of purchased product / receiving inspection). Under CP 7382.850, "Outsourcing & Purchasing" is a standalone QMS Area — elevated attention vs. QSIT.
2. **Formats:** **ASL/AVL:** class B master list (supplier → approved commodities → status → risk class → last audit/re-eval date). **Supplier qualification packages:** class C (questionnaires, ISO cert copies — often scans, class E; capability assessments). **Supplier audit reports:** class A narrative + finding tables. **SCARs:** class C form (8D format common: D1–D8 sections). **Quality agreements:** class A/E legal-style signed contracts (change-notification clauses, sub-tier flow-down, record retention, right-to-audit). **Receiving records:** class D (CoC/CoA scans, incoming inspection data per PN).
3. **Chunking:** ASL rows = edges. Audit reports: chunk per finding; extract finding table (finding # → clause → classification → response due). 8D SCARs chunk per discipline. Quality agreements chunk per clause; extract change-notification and sub-tier clauses specifically (top audit questions).
4. **Metadata:** supplier ID/name, status (approved/conditional/disqualified), risk category, commodity codes, cert expiry dates, audit dates + result, SCAR counts, agreement effective date.
5. **Cross-refs:** Supplier → PNs supplied (→ BOM where-used → finished devices affected — recall-critical); → incoming NCRs → SCARs → supplier CAPA responses → effectiveness; → supplier audits → findings → re-evaluation decisions; → quality agreement; supplier performance metrics → management review; supplier change notifications → ECO/impact assessments; CoA/CoC lot #s → DHR component-lot fields.
6. **Volume:** 50–500 suppliers; 5–30 supplier audits/yr (10–30 pp each); 10–100 SCARs/yr; agreements 10–40 pp each; receiving records scale with lots (thousands/yr).
7. **Auditor focus:** Risk-based qualification rationale; critical/single-source suppliers and contract sterilizers (always sampled); "supplier X had 15 rejects — show re-evaluation"; unqualified-supplier purchases (ASL vs. PO data cross-check); change-notification clause enforcement.

### 3.13 Customer Complaints
1. **Purpose/basis:** Old 820.198 (complaint files, designated unit, MDR-reportability evaluation, investigation requirements); now ISO 13485 § 8.2.2 + **§ 820.35(a)** (record content: complaint info per Part 803, whether investigated, rationale if not, MDR decision). Feeds ISO 14971 Cl. 10 post-production surveillance.
2. **Formats:** Class C form/eQMS workflow: intake (verbatim customer text, often emails/call logs attached), device identification, event coding (IMDRF adverse event codes increasingly), investigation, MDR decision tree, returned-product evaluation (DHR review + returned-unit analysis), response letter, closure; complaint log (class B).
3. **Chunking:** Intake narrative, investigation narrative, and MDR-decision rationale as separate chunks (each is separately queried); decision-tree fields structured. Preserve verbatim customer language (auditors compare it to the coded event).
4. **Metadata:** complaint #, receive date, aware date (MDR clock!), product/catalog/lot/serial, event codes (device problem code, patient problem code — FDA/IMDRF code sets), patient harm y/n, MDR-reportable decision + date, investigation y/n + rationale, closure date, country (for EU vigilance parallel).
5. **Cross-refs:** Complaint → device lot/serial → DHR; → MDR report # (if escalated) and/or vigilance reports; → NCR (returned product nonconformance); → CAPA (individually or via trend); → risk file hazard IDs (was this a foreseen harm? probability update); → service records (if from service); → complaint-handling SOP rev; trend reports → management review.
6. **Volume:** Wildly device-dependent: 100–20,000/yr; files 3–30 pp each. One of the two largest record families with DHRs.
7. **Auditor focus:** Always sampled. Aware-date → MDR-decision timeline (30-day clock); rationale quality for "not investigated" and "not reportable" decisions; complaint→risk-file feedback; trending methodology and CAPA escalation thresholds; consistency between complaint codes and MDR filings (FDA pre-pulls your MAUDE data before arriving).

### 3.14 MDR / Adverse Event Files (eMDR, MedWatch 3500A)
1. **Purpose/basis:** 21 CFR Part 803: § 803.17 (written MDR procedures), § 803.18 (MDR event files — must contain evaluation deliberations and decision documentation), § 803.50/.52 (manufacturer 30-calendar-day reports of deaths/serious injuries/malfunctions, content requirements), § 803.53 (5-work-day reports: events requiring remedial action to prevent unreasonable risk of substantial harm, or FDA-designated), § 803.56 (supplemental reports). Electronic submission (eMDR via ESG, HL7 ICSR XML rendering Form FDA 3500A) is mandatory for manufacturers.
2. **Formats:** Class G (eMDR XML + ESG acknowledgments ACK1/2/3) + class C (internal decision records) + 3500A PDF renders. 3500A sections: A (patient), B (event narrative + problem codes), D (suspect device: brand, model, catalog, lot, serial, UDI, operator), E/F, G (manufacturer info), H (device manufacturer narrative/evaluation codes: method/results/conclusion codes).
3. **Chunking:** Parse XML natively — field-to-property mapping; the B.5 event narrative and H.10 manufacturer narrative are the embeddable prose. Keep ACK trail (submission proof) as structured metadata.
4. **Metadata:** MDR report key: **manufacturer report number = FEI-year-sequence (e.g., 1234567-2026-00012)**, event date, aware date, report date (received-to-filed delta), report type (30-day/5-day/supplemental), event type (death/serious injury/malfunction), device problem codes, patient problem codes, follow-up #.
5. **Cross-refs:** MDR → source complaint #; → device lot/serial → DHR; → returned-device evaluation; → related MDRs (same event, multiple patients); → remedial action → correction/removal report (Part 806) → recall #; → risk file (severity/occurrence check); → CAPA; → PMA postapproval reporting if condition-of-approval study relevant; 5-day report → the remedial action driving it.
6. **Volume:** 10–2,000+/yr depending on device; files 10–40 pp each incl. deliberation records.
7. **Auditor focus (OAFR — checked at essentially every inspection):** Reconcile complaint log vs. MDRs filed (under-reporting is the classic 483); decision documentation for non-reported deaths/serious injuries; timeliness metrics; supplemental report follow-through; procedures per 803.17 current.

### 3.15 Clinical Trial Data & Reports (IDE, protocols, CRFs, CSRs, CER)
1. **Purpose/basis:** 21 CFR Part 812: § 812.20 (IDE application incl. report of prior investigations + investigational plan), § 812.25 (investigational plan: purpose, protocol, risk analysis, device description, monitoring, labeling, consent, IRB info), § 812.140 (records: sponsor — correspondence, shipment/disposition, signed investigator agreements, adverse device effects; investigator — case histories/CRFs, device accountability, consent, protocol deviations), § 812.150 (reports: UADEs within 10 working days to sponsor/IRB, sponsor annual progress reports, final report). Plus GCP (ISO 14155), and Clinical Evaluation Reports (EU MDR Annex XIV / MEDDEV 2.7/1 rev 4 structure) used for benefit-risk in the risk file even for US-focused firms.
2. **Formats:** Protocols/CSRs/CERs: class A narrative (CSRs 100–1,000 pp with statistical appendices, ICH-E3-like structure). CRFs: class C/E (eCRF exports or scanned paper forms per subject per visit). SAS/statistical datasets (SDTM-like). Monitoring reports, site files (1572-equivalents = investigator agreements), IRB correspondence: class C/E.
3. **Chunking:** Protocol: chunk per section (objectives, endpoints, inclusion/exclusion, statistical plan — each separately queried). CSR: efficacy/safety results sections + adverse event tables (structured extraction of AE tables). CER: per MEDDEV section (state of the art, equivalence, clinical data appraisal). CRFs: per-subject metadata extraction, not embedding.
4. **Metadata:** study ID/IDE #(G-number, e.g., G250042), protocol # + amendment #, site #s, subject IDs (pseudonymized), enrollment dates, endpoints, CSR version, CER rev + date range of literature search.
5. **Cross-refs:** IDE → investigational plan → protocol → amendments → IRB approvals; protocol → CRF template → subject CRFs → datasets → CSR tables; UADE → MDR-analog reporting + risk file; CSR → PMA clinical section (module cross-ref); CER → literature refs, complaint/PMS data, risk file benefit-risk (Cl. 8), post-market clinical follow-up plan; investigator → agreements → training → monitoring findings → deviations.
6. **Volume:** Pivotal Class III study: protocol 50–150 pp; 100–2,000 subjects × 20–200 pp CRFs (huge, mostly metadata-only ingest); CSR 200–1,000 pp; CER 50–300 pp, updated annually/biennially.
7. **Auditor focus:** FDA BIMO inspections (distinct from QSIT/QMSR track): consent, device accountability, protocol deviation handling, CRF↔source data integrity. Notified bodies: CER currency, literature search reproducibility, equivalence justification, PMCF execution.

### 3.16 Training Records
1. **Purpose/basis:** Old 820.25; ISO 13485 § 6.2 (competence, training, awareness, **effectiveness evaluation** proportionate to risk, records retained).
2. **Formats:** Class D/B: training matrix (role × required curriculum grid — Excel or LMS export), individual training records (sign-off sheets, often scanned class E; LMS completion exports; quiz/assessment results), curricula definitions, job descriptions, qualification/certification records (e.g., solder cert, visual inspection cert with eye-exam records).
3. **Chunking:** Almost pure structured data — ingest matrix and completion rows as graph edges; embed only curricula descriptions and effectiveness rationales.
4. **Metadata:** employee ID, role, curriculum/course ID → SOP # + **rev trained on**, completion date, trainer, method (read-and-understand/classroom/OJT), effectiveness assessment, due/expiry (for recurring).
5. **Cross-refs:** Person → SOP/WI revs trained (time-stamped — must precede the records they signed!); role → curriculum → SOP set; SOP rev change (ECO) → retraining triggers → completion evidence; CAPA corrective actions → retraining records; DHR operator initials → person → training status on build date; auditor/reviewer qualifications → audit reports.
6. **Volume:** headcount × 20–200 items; 10k–100k rows; individual evidence 1–3 pp each.
7. **Auditor focus:** The date-math trap: "Operator J signed DHR step 12 on March 3; show J was trained on WI-014 Rev C effective March 1." Effectiveness evaluation evidence (not just sign-offs); trainer qualification; training on the *current* rev.

### 3.17 Equipment, Calibration & Maintenance Records
1. **Purpose/basis:** Old 820.72 (calibration: traceable standards, records incl. out-of-tolerance impact) & 820.70(g) (maintenance); ISO 13485 § 7.6 (monitoring & measuring equipment, calibration traceable, **assessment of validity of prior results when found out-of-tolerance**, records) & § 6.3 (infrastructure/maintenance).
2. **Formats:** Class B asset master (asset # → description → location → cal interval → due date); class D/E calibration certificates (external labs: ISO 17025 certs with as-found/as-left data tables, standard IDs w/ NIST traceability); maintenance logs/PM work orders (CMMS exports); equipment qualification (IQ/OQ) reports (class A).
3. **Chunking:** Asset master = nodes; certs: extract as-found/as-left, pass/fail, cal date, due date, standards used; OOT investigations = narrative chunks (impact assessments).
4. **Metadata:** asset/gauge ID, serial, model, location, cal interval + basis, last/next cal date, status (active/OOT/retired), tolerance class.
5. **Cross-refs:** Asset → cal certs (time series); OOT cert → impact assessment → affected measurements → DHRs/test reports using that asset in the window → NCRs if product impact; asset → IQ/OQ/PQ validations; asset → PM records; test protocols/reports and DHR steps → asset IDs used (edge extracted from those docs); control plan lines → gauge IDs.
6. **Volume:** 100–2,000 assets × 1–4 events/yr; certs 2–6 pp.
7. **Auditor focus:** Pick equipment on the floor → "show current cal sticker vs. record"; OOT handling — the reverse-traceability question ("this gauge failed calibration in June; what product did it accept since March?") is exactly a graph query; unvalidated equipment in validated processes.

### 3.18 Internal Audit Reports
1. **Purpose/basis:** Old 820.22; ISO 13485 § 8.2.4 (planned intervals, criteria/scope/frequency defined, auditor impartiality, records, corrections without undue delay). Historically FDA reviewed only *certification* that audits occurred (old policy against routinely copying audit results); reportedly under CP 7382.850 audit reports are within inspection scope — verify against the CP itself; notified bodies always review them in full.
2. **Formats:** Annual audit schedule/program (class B); audit plans/agendas; audit reports (class A narrative + finding tables: finding # → clause → objective evidence → classification major/minor/OFI); auditor qualification records; finding responses → CAPA links.
3. **Chunking:** Per-finding chunks with clause + evidence; schedule as structured rows.
4. **Metadata:** audit #, dates, scope (process/clause/site), auditors (independence!), findings count by class, status.
5. **Cross-refs:** Audit → processes/SOPs audited → clauses; finding → CAPA #; audit program → risk rationale for frequency; findings trends → management review; previous-audit findings → verification of closure in next audit; auditor → qualification/training records.
6. **Volume:** Full QMS coverage/yr typical: 10–30 audits/yr, reports 5–25 pp.
7. **Auditor focus:** Schedule adherence; coverage of all processes incl. remote/outsourced; auditor independence from audited area; findings actually flowed to CAPA; repeat findings (system failure signal).

### 3.19 Management Review
1. **Purpose/basis:** Old 820.20(c); ISO 13485 § 5.6 — documented intervals; **required inputs** (5.6.2: feedback, complaint handling, regulatory reporting, audits, process/product monitoring, CAPA, follow-up from prior reviews, changes affecting QMS, improvement recommendations, new/revised regulatory requirements) and **outputs** (5.6.3: improvements, resource needs, changes needed).
2. **Formats:** Class A/C: agenda + slide deck (PowerPoint→PDF — chunking hazard: sparse-text slides with dense charts) + minutes + action item table + attendance.
3. **Chunking:** Per required-input section (map slides/minutes to the 5.6.2 input list — auditors check every input was covered); action items structured; metric charts need table/figure extraction or alt-text summarization.
4. **Metadata:** review date, period covered, attendees (top management presence!), inputs covered checklist, action items + owners + due dates.
5. **Cross-refs:** Review → data sources presented (complaint trend report IDs, CAPA log snapshot, audit summaries, supplier metrics, quality objectives dashboard); → actions → CAPAs/projects spawned; → prior review action closure; → quality policy/objectives revisions; → resource decisions.
6. **Volume:** 1–4/yr; packages 30–150 pp.
7. **Auditor focus:** First records requested under both QSIT (Management Controls) and CP 7382.850 (record prioritization starts here): all required inputs addressed, evidence of *risk-based decisions* not metric theater, actions completed, top management actually present.

### 3.20 Labeling and IFU
1. **Purpose/basis:** 21 CFR Part 801 (content, UDI on label per 801 Subpart B + Part 830/GUDID); **§ 820.45** (retained QMSR-specific labeling/packaging controls: examination for accuracy incl. UDI, expiry, storage/handling instructions; release documentation; label integrity/legibility); ISO 13485 § 7.5.1(d)/7.3.4 (labeling as design output). IFU content also driven by IEC 62366 (information for safety = risk controls) and PMA-approved labeling (approved as part of the PMA — changes may need supplements per 814.39).
2. **Formats:** Class F/A: label artwork files (Illustrator→PDF proofs with dielines), IFU booklets (multi-language, 20–200 pp), carton/pouch artwork, eIFU postings, GUDID data (class G), label specs (class A), translation certificates.
3. **Chunking:** IFU: chunk per section (indications, contraindications, warnings/precautions, instructions, symbols glossary [ISO 15223], technical specs); label artwork: extract text layers + symbol inventory; keep language variants linked as one logical label with variants.
4. **Metadata:** label/IFU PN + rev, product + catalog #s covered, UDI-DI, language set, approved-labeling baseline (PMA supplement #), artwork approval dates.
5. **Cross-refs:** Label PN → BOM (labels are BOM items) → DHR label-reconciliation steps; IFU warnings → risk file "information for safety" controls (RC IDs); IFU claims → PMA approved labeling → clinical evidence; label rev → ECO → regulatory assessment (labeling changes are supplement-sensitive); UDI-DI → GUDID record → MDR/recall device identification; symbols → ISO 15223 registry.
6. **Volume:** 50–500 label/IFU items × revisions; artwork files + specs.
7. **Auditor focus:** § 820.45 examination/release records for a sampled lot; label reconciliation math in DHRs; IFU warnings vs. risk file consistency; UDI correctness vs. GUDID; whether marketed labeling matches PMA-approved labeling.

### 3.21 Sterilization Validation
1. **Purpose/basis:** Process validation obligation (13485 § 7.5.6/7.5.7, legacy 820.75) executed per ISO 11135 (EO: IQ/OQ/PQ with half-cycle or overkill methods, EO residuals per ISO 10993-7), ISO 11137-1/-2 (radiation: dose setting VDmax25/Method 1, quarterly dose audits), ISO 17665 (moist heat); supported by ISO 11737-1 (bioburden) and -2 (sterility tests); packaging sterile-barrier per ISO 11607. A QSIT satellite historically; contract sterilizers make this a supplier-control intersection.
2. **Formats:** Class A validation protocols/reports (heavy tables: cycle parameters, BI/CI placements, load maps/diagrams, thermocouple data) + class D routine records (per sterilization load: cycle printouts, BI results, release records) + class E lab reports (contract labs: bioburden, sterility, residuals, dose audits — Nelson Labs-style certs).
3. **Chunking:** Protocol/report per section; cycle-parameter tables and acceptance tables structured; load maps as figures with caption extraction; routine load records = per-load field extraction (load #, cycle #, date, product lots inside, parameters, BI result, released by).
4. **Metadata:** validation # + rev, sterilization modality, cycle ID, sterilizer asset/site (contract sterilizer name + facility), SAL claim (10⁻⁶), product families/load configurations qualified, requalification due date, dose audit cadence.
5. **Cross-refs:** Validation → product families/PNs qualified (adoption/equivalence assessments for new PNs!); → sterilizer equipment/IQ; → contract sterilizer (supplier file, quality agreement); routine load # → finished-goods lots sterilized (DHR linkage — recall-critical); → BI lot certs; dose audit failures → NCR/CAPA + dose augmentation; ECOs changing product/packaging → revalidation assessments; → PMA sterilization section.
6. **Volume:** Per modality/family: validation package 100–500 pp; requalification annually/biennially; routine load records = hundreds–thousands/yr; quarterly dose audits (radiation).
7. **Auditor focus:** Perennial deep-dive for sterile Class III: validation-to-current-product match ("you added PN X to the load — where's the adoption rationale?"), requalification currency, load release records, parametric vs. BI release basis, contract sterilizer oversight.

### 3.22 Biocompatibility Reports
1. **Purpose/basis:** Design verification of biological safety per ISO 10993-1 (evaluation within risk management — categorize by contact type/duration → endpoint matrix) + part-specific tests (-5 cytotoxicity, -10/-23 sensitization/irritation, -11 systemic toxicity, -3 genotoxicity, -4 hemocompatibility, -6 implantation, -17/-18 chemical characterization + toxicological risk assessment); FDA's ISO 10993-1 guidance drives US expectations. PMA biocompatibility section.
2. **Formats:** Class A: Biological Evaluation Plan (BEP) + Biological Evaluation Report (BER) + individual contract-lab study reports (GLP-format: protocol, results, QA statement — class A/E scans) + chemical characterization data (E&L tables) + toxicological risk assessments.
3. **Chunking:** BEP/BER per endpoint (the endpoint matrix — contact category × endpoint × evidence — is the structured core); lab reports: summary/conclusion chunks + protocol metadata; E&L compound tables structured.
4. **Metadata:** study #s (lab report #s), test article PN + **material/formulation rev + processing state (sterilized? aged?)**, GLP status, endpoints covered, lab name.
5. **Cross-refs:** BER → endpoint matrix → study reports; test article → material specs/supplier (→ material change notifications trigger re-evaluation — the killer edge: supplier resin change → biocomp impact assessment); → sterilization modality (test articles must be representative); → risk file (biological hazards); → PMA section; ECO material changes → biocomp gap assessments.
6. **Volume:** 10–40 study reports (10–100 pp each) + BEP/BER (30–150 pp); refreshed on material/process changes.
7. **Auditor focus:** Test articles representative of final (sterilized, aged) device; endpoint coverage vs. current 10993-1 matrix; material/supplier changes since testing ("your resin supplier changed in 2024 — where's the biological re-evaluation?").

### 3.23 Software Documentation (IEC 62304)
1. **Purpose/basis:** IEC 62304 lifecycle, rigor scaled by safety class (A: requirements + release minimum; B: + architecture, integration testing, problem resolution rigor; C: + detailed design, full unit verification). Deliverables: software development plan (5.1), software requirements spec (5.2), architecture (5.3), detailed design (5.4, Class C), unit implementation/verification (5.5), integration tests (5.6), system tests (5.7), release records incl. known-anomaly list (5.8); maintenance plan (Cl. 6); software risk (Cl. 7, ties to 14971); configuration management (Cl. 8, **SOUP list** per 8.1.2 — item, version, manufacturer, known anomalies); problem resolution (Cl. 9 — bug tracker). FDA premarket software guidance (2023, "documentation level" Basic/Enhanced) governs the PMA software section; cybersecurity docs (SBOM, threat model per FDA 524B guidance) now expected.
2. **Formats:** Class A plans/specs + ALM/issue-tracker exports (Jira/Azure DevOps — class B/G), test automation results (XML/HTML reports), SBOM (SPDX/CycloneDX JSON — class G), code review records, build/release records (CI manifests).
3. **Chunking:** Specs per requirement/component; anomaly lists and SOUP lists row-level; release notes per release; keep requirement↔test↔anomaly IDs intact.
4. **Metadata:** software item names + safety class per item, release/version (semver), SRS/SDS doc #s + revs, build IDs, anomaly IDs, SOUP component+version.
5. **Cross-refs:** Software system → items → units (class per item); SRS req → system req (product level) → architecture components → tests → results; anomalies (bug IDs) → releases fixed-in → complaint IDs (field bugs) → risk assessments (unresolved-anomaly justifications at release); SOUP entry → version → known-anomaly review → risk file; release → PMA supplement/letter-to-file decision; SBOM components → vulnerability monitoring records → cybersecurity risk assessments.
6. **Volume:** Per release: SRS 100–1,000 reqs, test reports hundreds of pp, anomaly DB thousands of rows; multiple releases/yr.
7. **Auditor focus:** Safety classification rationale per item; unresolved anomalies at release with risk-based justification; SOUP control; regression scope rationale per change; cybersecurity postmarket monitoring (increasingly).

### 3.24 Change Control (ECO/ECN/DCO — document and engineering changes)
1. **Purpose/basis:** ISO 13485 § 4.2.4 (document changes reviewed/approved by original function or designee), § 7.3.9 (design changes); a dedicated "Change Control" QMS Area under CP 7382.850 — FDA elevated it because unassessed changes are a systemic failure mode. Covers doc-only changes (DCO), engineering changes (ECO/ECN), process changes (MCO), each with risk + regulatory + validation impact assessments.
2. **Formats:** Class C forms/PLM workflow records; redline attachments.
3. **Chunking:** As § 3.2.8; the impact-assessment checkboxes+rationales are the audit meat.
4. **Metadata:** change #, type, affected items table (doc/PN old→new rev), effectivity (date/lot/serial), disposition of WIP/inventory, approvals.
5. **Cross-refs:** As § 3.2.8 — the ECO node is the temporal join between every document family's revision histories. Every "Rev C" in every revision-history table should resolve to an ECO node.
6. **Volume:** 100–1,000 changes/yr.
7. **Auditor focus:** "List changes since last inspection" is the standard opener under CP 7382.850's Change Control area; sampled for impact-assessment completeness, V&V of the change, regulatory reporting decision (814.39 supplement vs. annual report), and effectivity discipline.

### 3.25 Regulatory Submissions (PMA sections, annual reports, supplements)
1. **Purpose/basis:** 21 CFR 814.20 (PMA content: summaries, device description, nonclinical + clinical study sections, manufacturing section describing the QMS/facilities, proposed labeling, environmental assessment); 814.39 (supplements: panel-track, 180-day, real-time, 30-day notice for manufacturing changes, Special PMA Supplement — Changes Being Effected); 814.84 (periodic/annual reports: changes not requiring supplements, publication bibliography, devices shipped/sold); postapproval study (PAS) reports per approval order conditions. Also device listing/establishment registration (Part 807 Subparts B–D).
2. **Formats:** eCopy/eSTAR structured volumes (class G folder trees with per-section PDFs); FDA correspondence (deficiency letters, approval orders — class A/E); supplement packages; annual report packages.
3. **Chunking:** Per section per the PMA shell (each section maps to internal evidence: the manufacturing section ↔ DMR/SOPs, nonclinical ↔ verification reports, clinical ↔ CSR); FDA questions + responses as Q/A pairs (highly queried during audits: "what did you tell FDA about X?").
4. **Metadata:** PMA # (P-number, e.g., P240015), supplement #s (S001…), submission dates, approval dates, approval-order conditions, annual report period.
5. **Cross-refs:** PMA section → source documents in DHF/RMF/clinical (a submission-to-source index is enormously valuable — build it); approval order conditions → PAS protocols/reports → annual reports; supplements → ECOs implemented; annual report change list → ECO log reconciliation (auditors and FDA reviewers do this diff); approved labeling → current labeling revs.
6. **Volume:** Original PMA 10k–100k pp; 2–20 supplements/yr for an active device; annual reports 20–200 pp.
7. **Auditor focus:** Field investigators check consistency: device being built matches the PMA (manufacturing section vs. observed process); changes made vs. changes reported (ECO log vs. supplements/annual reports); approval-order conditions honored.

### 3.26 Corrections & Removals / Recalls (21 CFR 806)
1. **Purpose/basis:** § 806.10 (report to FDA within 10 working days of initiating a correction/removal to reduce a risk to health or remedy a violation that may present a risk to health); § 806.20 (records of corrections/removals **not** required to be reported, with justification, retained). Health hazard evaluations (HHE) support recall classification; links to Part 7 recall procedures.
2. **Formats:** Class C: recall strategy documents, HHE forms (signed by medical officer), FDA correspondence, consignee lists (class B — DHR shipment data), effectiveness-check records (response tracking tables), termination requests.
3. **Chunking:** HHE narrative + strategy sections; consignee/response tables structured.
4. **Metadata:** correction/removal #, FDA recall # (Z-numbers), class (I/II/III), initiation date, scope (lots/serials/date range), depth (user/retail), status, termination date.
5. **Cross-refs:** Recall → triggering complaint/MDR/NCR/CAPA; → HHE → risk file; → affected lots (DHR genealogy defines scope — the recall-scope query is a pure graph traversal); → consignees (shipment records); → 806.10 report or 806.20 justification record; → correction instructions (field service docs); → effectiveness checks; → CAPA closing the root cause.
6. **Volume:** 0–5/yr (hopefully); packages 50–500 pp.
7. **Auditor focus (OAFR):** 806.20 files ("you fixed this quietly — show the documented non-reportability rationale"); scope adequacy (did lot genealogy support the cut-line?); effectiveness check rigor; timeliness of the 10-working-day report.

---

## 4. Proposed Knowledge Graph Schema (Neo4j)

### 4.1 Entity (node) types

| # | Label | Key property | Core properties | Source of truth |
|---|---|---|---|---|
| 1 | `Document` (supertype; secondary label per family, e.g. `:Document:SOP`) | docNumber + revision (composite) | title, family, structuralClass, effectiveDate, status, ownerRole | eQMS/PLM metadata + header extraction |
| 2 | `DocumentRevision` | docNumber+rev | effectiveDate, supersedes, changeOrderId | revision-history tables |
| 3 | `RegClause` | regime+clause (e.g. `21CFR:820.35`, `ISO13485:8.2.2`, `ISO14971:4.5`, `IEC62304:5.3`) | text summary | static reference data |
| 4 | `Product` | productId | name, class, pmaNumber, udiDi[] | reg. files/GUDID |
| 5 | `PartNumber` | pn+rev | description, type (assy/component/label/software) | PLM/BOM |
| 6 | `Lot` / `SerialUnit` | lotNumber / serialNumber | mfgDate, qty, expiry, dispositionStatus | DHR |
| 7 | `Supplier` | supplierId | name, status, riskClass, commodities[] | ASL |
| 8 | `Equipment` | assetId | description, location, calInterval, calDueDate | asset master |
| 9 | `Person` | employeeId | name, role, dept | HR/LMS |
| 10 | `TrainingItem` | curriculumId | linked doc+rev | LMS |
| 11 | `UserNeed` / `Requirement` | reqId | text, category, verifyMethod | req docs / trace matrix |
| 12 | `DesignOutput` | doc/drawing # + rev | type | DHF/DMR |
| 13 | `Hazard`, `HazardousSituation`, `Harm` | hazId/hsId/harmId | severity, P1/P2, riskLevel(pre/post) | RMF hazard analysis |
| 14 | `RiskControl` | rcId | type (inherent safety / protective / info-for-safety), status | RMF |
| 15 | `FailureMode` (FMEA line) | fmeaId+line | S,O,D,RPN/AP, type(D/P) | FMEA worksheets |
| 16 | `ControlPlanItem` | cpId+line | characteristic, method, frequency | control plans |
| 17 | `TestActivity` (protocol/report pair) | protocolId | type (verification/validation/HF/process), result | V&V docs |
| 18 | `Complaint` | complaintId | receiveDate, awareDate, eventCodes[], harmFlag, mdrDecision | complaint system |
| 19 | `MDRReport` | mfrReportNumber (FEI-year-seq) | reportType, eventType, dates | eMDR XML |
| 20 | `NCR` | ncrId | source, defectCode, disposition, dates | NCR forms/log |
| 21 | `CAPA` | capaId | source, phase, dates, effectivenessResult | CAPA records |
| 22 | `Deviation` | devId | type, window, affectedDoc | deviation forms |
| 23 | `SCAR` | scarId | status, dates | supplier system |
| 24 | `Audit` (internal/supplier/external) | auditId | type, dates, scope | audit reports |
| 25 | `Finding` | findingId | classification, clause, status | audit reports |
| 26 | `ManagementReview` | mrId | date, period | MR minutes |
| 27 | `ChangeOrder` (ECO/DCO/MCO) | changeId | type, effectivity, regDecision | change forms |
| 28 | `Submission` | submissionId (P#/S#/annual-report-year) | type, dates, status | reg. affairs |
| 29 | `RecallEvent` | recallId (+FDA Z#) | class, scope, status | 806 files |
| 30 | `ClinicalStudy` | studyId (IDE G#) | phase, endpoints | clinical files |
| 31 | `Site` / `Investigator` | siteId | — | clinical files |
| 32 | `SterilizationLoad` / `SterilizationValidation` | loadId / valId | modality, cycle, result | sterilization records |
| 33 | `SoftwareItem` / `SoftwareRelease` | itemId / version | safetyClass | 62304 docs |
| 34 | `SoupComponent` | name+version | knownAnomalies | SOUP list/SBOM |
| 35 | `Anomaly` (bug) | bugId | severity, status, fixedIn | issue tracker |
| 36 | `LabelItem` (label/IFU) | labelPn+rev | languages[], udiDi | labeling |
| 37 | `Chunk` (RAG text unit) | chunkId | text, embedding, page, section | ingestion |

Every record/document node gets `MENTIONS`/`PART_OF` edges to `Chunk` nodes so graph traversal can land on citable text with page numbers — auditors require page-level citations.

### 4.2 Edge types (directional)

Document/control backbone:
- `(Document)-[:SUPERSEDES]->(DocumentRevision)` ; `(Document)-[:CHANGED_BY]->(ChangeOrder)`
- `(Document)-[:IMPLEMENTS]->(RegClause)` ; `(Document)-[:REFERENCES]->(Document)` (from References sections + inline "per SOP-xxx")
- `(Document:Form)-[:TEMPLATE_FOR]->(record nodes)` ; `(SOP)-[:PARENT_OF]->(WI)`
- `(DMR|MedicalDeviceFile)-[:COMPRISES {rev}]->(Document|DesignOutput|LabelItem)` ; `(DHF)-[:COMPRISES]->(Document)`

Design/trace thread:
- `(Requirement)-[:DERIVED_FROM]->(UserNeed)` ; `(DesignOutput)-[:SATISFIES]->(Requirement)`
- `(TestActivity)-[:VERIFIES]->(Requirement|DesignOutput)` ; `(TestActivity)-[:VALIDATES]->(UserNeed)`
- `(TestActivity)-[:TESTED_ARTICLE]->(Lot|SerialUnit)` ; `(TestActivity)-[:USED_EQUIPMENT]->(Equipment)`
- `(TestActivity)-[:HAD_DEVIATION]->(Deviation)` ; `(TestActivity)-[:RAISED]->(NCR)`
- `(PartNumber)-[:CHILD_OF {qty}]->(PartNumber)` (BOM) ; `(DesignOutput)-[:DEFINES]->(PartNumber)`

Risk thread:
- `(Hazard)-[:MANIFESTS_AS]->(HazardousSituation)-[:LEADS_TO {p2}]->(Harm)`
- `(RiskControl)-[:MITIGATES]->(HazardousSituation)` ; `(RiskControl)-[:IMPLEMENTED_BY]->(DesignOutput|LabelItem|Document)`
- `(TestActivity)-[:VERIFIES_CONTROL]->(RiskControl)`
- `(FailureMode)-[:FEEDS]->(Hazard)` ; `(FailureMode)-[:CONTROLLED_BY]->(ControlPlanItem)` ; `(ControlPlanItem)-[:MEASURED_WITH]->(Equipment)`
- `(Complaint|MDRReport|Anomaly)-[:EVALUATED_AGAINST]->(Hazard)` (post-production feedback, ISO 14971 Cl. 10)

Production thread:
- `(Lot)-[:BUILT_PER]->(DMR rev)` ; `(Lot)-[:CONSUMED {qty}]->(Lot)` (genealogy) ; `(Lot)-[:SUPPLIED_BY]->(Supplier)`
- `(Lot)-[:PROCESSED_ON]->(Equipment)` ; `(Lot)-[:STEP_PERFORMED_BY {step, date}]->(Person)`
- `(Lot)-[:STERILIZED_IN]->(SterilizationLoad)-[:QUALIFIED_BY]->(SterilizationValidation)`
- `(Person)-[:TRAINED_ON {date, rev}]->(TrainingItem)-[:COVERS]->(Document rev)`
- `(Equipment)-[:CALIBRATED {date, result, cert#}]->(CalibrationEvent)` ; `(CalibrationEvent:OOT)-[:IMPACT_ASSESSED_BY]->(NCR|Assessment)`

Quality-event thread (CAPA hub):
- `(Complaint)-[:INVOLVES]->(Lot|SerialUnit|Product)` ; `(Complaint)-[:ESCALATED_TO]->(MDRReport)` ; `(Complaint)-[:TRIGGERED]->(NCR|CAPA)`
- `(NCR)-[:CONCERNS]->(PartNumber|Lot)` ; `(NCR)-[:ATTRIBUTED_TO]->(Supplier)` ; `(NCR)-[:ESCALATED_TO]->(CAPA)` ; `(SCAR)-[:ISSUED_TO]->(Supplier)` ; `(SCAR)-[:SOURCED_FROM]->(NCR)`
- `(CAPA)-[:SOURCED_FROM]->(Complaint|NCR|Finding|MDRReport|Deviation|SCAR|TrendReport)`
- `(CAPA)-[:IMPLEMENTED_VIA]->(ChangeOrder|TrainingItem)` ; `(CAPA)-[:VERIFIED_BY]->(EffectivenessCheck)` ; `(CAPA)-[:UPDATED]->(RMF doc|FailureMode)`
- `(Audit)-[:PRODUCED]->(Finding)-[:CITES]->(RegClause)` ; `(Finding)-[:RESOLVED_BY]->(CAPA)`
- `(ManagementReview)-[:REVIEWED]->(TrendReport|CAPA|Audit|Complaint summary)` ; `(ManagementReview)-[:SPAWNED]->(ActionItem)`

Regulatory/postmarket thread:
- `(Submission)-[:CONTAINS]->(Document)` (submission-to-source index) ; `(Submission:Supplement)-[:AUTHORIZES]->(ChangeOrder)` ; `(Submission:AnnualReport)-[:REPORTS]->(ChangeOrder)`
- `(RecallEvent)-[:TRIGGERED_BY]->(Complaint|MDRReport|NCR)` ; `(RecallEvent)-[:SCOPED_TO]->(Lot)` ; `(RecallEvent)-[:REPORTED_VIA]->(806Report)` ; `(RecallEvent)-[:CLOSED_BY]->(CAPA)`
- `(ClinicalStudy)-[:CONDUCTED_AT]->(Site)` ; `(ClinicalStudy)-[:GOVERNED_BY]->(Document:Protocol)` ; `(CSR)-[:SUMMARIZES]->(ClinicalStudy)` ; `(CER)-[:APPRAISES]->(CSR|Literature|Complaint data)`
- `(SoftwareRelease)-[:PART_OF]->(Product)` ; `(SoftwareItem)-[:INCLUDES]->(SoupComponent)` ; `(Anomaly)-[:AFFECTS]->(SoftwareItem)` ; `(Anomaly)-[:FIXED_IN]->(SoftwareRelease)` ; `(SoftwareRelease)-[:ASSESSED_BY]->(ChangeOrder)`

Design decision: revisions modeled as first-class (`DocumentRevision`) because audit answers are rev-sensitive ("training on Rev C, DHR cites Rev B" is a finding). All time-qualified edges (training, calibration, effectivity) carry date properties to support as-of-date queries — the single most common audit computation.

### 4.3 Extraction sources for edges, ranked by yield

1. Trace matrices (pure edge lists — ingest first)
2. DHF/DMR/RMF index documents (COMPRISES edges)
3. Form field values (CAPA source ids, NCR lot/PN, complaint device fields)
4. Revision history tables (SUPERSEDES, CHANGED_BY)
5. References sections of controlled docs (REFERENCES)
6. FMEA/hazard-analysis columns (risk edges)
7. Inline prose regex hits ("per SOP-021", "see NCR-2025-0143") — lowest precision; require doc-ID validation against the master doc register before edge creation

---

## 5. Document Numbering & Revision Conventions (ID extraction)

### 5.1 Observed convention families

| Pattern family | Examples | Notes |
|---|---|---|
| Type-prefix + serial | `SOP-001`, `SOP-0123`, `WI-045`, `FRM-012`, `QM-001`, `TM-003` | Most common; serial 2–5 digits, leading zeros inconsistent across eras |
| Type + dept/area + serial | `WI-MFG-014`, `SOP-QA-007`, `F-ENG-102` | Middle token = functional area |
| Clause-mapped | `QP-7.3-01`, `QP-820-40-01` | Procedure numbered by ISO/CFR clause — dots and hyphens interchange |
| Record-type + year + seq | `CAPA-2025-014`, `NCR-25-0157`, `DEV-2024-012`, `COMP-2026-0456`, `CMPL-…`, `SCAR-2025-009`, `AUD-2025-03` | Year 2 or 4 digits; seq zero-padded 3–5 |
| Change orders | `ECO-1042`, `ECN-24-118`, `DCO-2025-031`, `CO-0871` | Sometimes bare integers from PLM |
| Test docs (paired) | `TP-0451` / `TR-0451`, `VER-012-P` / `VER-012-R`, `STP-`/`STR-`, `VAL-`/`PQ-`/`OQ-` | Protocol/report share a stem — exploit for pairing |
| Requirements/risk items | `UN-012`, `PRD-1234`, `REQ-0456`, `SRS-078`, `HAZ-014`, `HS-023`, `RC-017`, `DFMEA-03 line 47` | ALM-tool IDs may be bare integers with tool prefix (`PROJ-1234` Jira-style) |
| Part/drawing numbers | `10-0456-02`, `PN 300-1234 Rev B`, `DWG-10-0456 Sh 2` | Numeric-segmented; collides with dates — validate against item master |
| MDR report number | `1234567-2026-00012` | FEI(7)-year(4)-seq(5) — high-precision regex |
| PMA/IDE | `P240015`, `P240015/S003`, `G250042` | Letter + 6 digits (+ `/Sxxx`) |
| FDA recall | `Z-1234-2026` | — |
| Lot/serial | `LOT 260117-01`, `L26A045`, `SN 004512` | Site-specific; date-encoded lots common |

### 5.2 Revision conventions

- Letter revs: `Rev A` → `Rev B` … (skip I, O, Q typically); pre-release numeric (`Rev 01`)→ letter at release, or the reverse. Compound (`Rev C2`, `Rev B.1`) for minor changes.
- Software/reg docs: semver-ish `v1.0`, `2.1`; submissions use sequence letters/amendment numbers.
- Status vocabulary: Draft / In Review / Pre-release / Released / Effective / Obsolete / Superseded — plus effective-date vs. approval-date distinction (documents are approved days before effective; auditors check the gap for training completion).
- Rev appears in: header/footer of every page, revision-history table, watermarks ("OBSOLETE", "UNCONTROLLED COPY"), filename (`SOP-021_RevC_Effective.pdf`), and eQMS metadata — reconcile all, trust eQMS metadata > rev table > footer > filename.

### 5.3 Practical regex bank (starting set — tune per site)

```
# Controlled doc IDs (prefix list per site config)
\b(?P<type>SOP|WI|QP|QM|FRM|FORM|F|TM|SPEC|DWG|STP|STR|TP|TR|VAL|PRO|RPT|PLN|BEP|BER|RMP|RMR)
[-_ ]?(?P<area>[A-Z]{2,4}[-_ ])?(?P<num>\d{2,5})(?:[-_ ]?(?:Rev|REV|rev\.?|R)[-_ ]?(?P<rev>[A-Z]{1,2}\d?|\d{1,2}))?\b

# Quality records (year-scoped)
\b(?P<type>CAPA|NCR|NCMR|MRB|DEV|SCAR|COMP|CMPL|CC|AUD|IA|ECO|ECN|DCO|MCO|CO|CR)
[-_ ]?(?P<year>\d{2}|\d{4})?[-_ ]?(?P<seq>\d{2,6})\b

# MDR manufacturer report number
\b\d{7}-\d{4}-\d{5}\b

# PMA / supplement / IDE / recall
\bP\d{6}(?:/S\d{3})?\b     \bG\d{6}\b     \bZ-\d{4}-\d{4}\b

# CFR / ISO clause cites (for RegClause linking)
\b21\s?CFR\s?(?:Part\s?)?(\d{3})(?:\.(\d+))?(?:\(([a-z])\))?\b
\bISO\s?(13485|14971|11135|11137|10993(?:-\d+)?|11607|15223|14155|62366(?:-1)?)\b(?::(\d{4}))?
\bIEC\s?(62304|62366(?:-1)?|60601(?:-\d+(?:-\d+)?)?)\b
```

Extraction rules that matter in practice: (1) validate every regex hit against the master document register / item master before creating an edge (false positives from dates, phone numbers, dimension callouts are rampant); (2) normalize separators (hyphen/en-dash/space/underscore) and leading zeros to a canonical key; (3) a doc ID in a page footer is self-reference, not a cross-reference — suppress; (4) IDs inside revision-history tables refer to change orders, inside References sections to dependencies, inline to operational links — record the *context* of the mention as an edge property; (5) OCR confusions to fold: O↔0, I↔1, S↔5, B↔8 in ID tokens.

---

## 6. Audit Structure → Query Patterns

### 6.1 QSIT (legacy, pre-Feb-2026 — still shapes auditor behavior and the corpus)

Four subsystems, inspected top-down (procedure first, then records sampled against it):

| Subsystem | Anchor (legacy cites) | Typical primary records sampled |
|---|---|---|
| Management Controls | 820.20, 820.22, 820.186 | Quality manual, management reviews, audit schedule + certification, org charts, quality plan/objectives |
| Design Controls | 820.30 | One project's DHF: plan → inputs → outputs → reviews → V&V → transfer → changes; trace matrix as the walkthrough map |
| CAPA (+ satellites: MDR, corrections/removals) | 820.100, 820.90, 803, 806 | CAPA log + sampled CAPAs; complaint log vs. MDR log reconciliation; NCR trends; 806 records |
| Production & Process Controls (+ satellite: sterilization) | 820.70–820.75, 820.80 | DHRs, process validations (IQ/OQ/PQ), calibration, training, environmental controls, sterilization validation + loads |

Sampling: QSIT sampling tables (binomial-based) — the investigator establishes the record population (e.g., all CAPAs in the last 2 years), then pulls a table-driven sample size to reach stated confidence that a systemic failure rate would be detected; findings are cited against the *system*, not the individual record. A one-week, 4-subsystem "comprehensive" inspection (biennial for Class III) vs. abbreviated (2 subsystems: always CAPA + one other).

### 6.2 CP 7382.850 (current, effective Feb 2, 2026)

Six QMS Areas: **Management Responsibility; Resource Management; Product Realization; Measurement, Analysis & Improvement; Outsourcing & Purchasing; Change Control** — each composed of "elements" mapped to ISO 13485 clauses + Part 820 additions. Four OAFRs: **MDR (803), Corrections & Removals (806), Tracking (821), UDI (801/830)**. Characteristics that change RAG query load:
- Risk-based: the manufacturer's **risk management file is the inspection roadmap**; product risk (MAUDE data, recalls) steers depth.
- Thread-tracing across functions: complaint → investigation → CAPA → design change → risk file update → management review — i.e., **multi-hop graph traversals are literally the inspection method.**
- Record prioritization: management review minutes, internal audit reports, complaint/CAPA data first; supplier audit reports and design-change records next (reported: internal/supplier audit reports no longer categorically exempt — verify against the CP text).
- Inspection types: surveillance (baseline/non-baseline), for-cause, compliance follow-up, PMA pre-approval/post-approval.

### 6.3 ISO 13485 / notified body / MDSAP audits

- Certification cycle: Stage 1 (doc review) → Stage 2 (implementation) → annual surveillance → 3-yr recertification. Process-approach auditing: follow a product through the process map; every clause sampled over the cycle, high-risk processes (design, CAPA, complaints, sterilization) every audit.
- MDSAP: task-based model (7 processes: Management; Device Marketing Authorization & Facility Registration; Measurement, Analysis & Improvement; Medical Device Adverse Events & Advisory Notices; Design & Development; Production & Service Controls; Purchasing) with country modules; nonconformities graded 1–5.
- Notified bodies additionally sample technical documentation (design dossier) — CER currency, risk file, PMS/PMCF data.

### 6.4 Top audit query patterns (design the retrieval API around these)

1. **Procedure fetch:** "Show me your procedure for X" → current-effective SOP by process area + section-level citation. (Filter: status=Effective, as-of date.)
2. **Record-population listing:** "List all CAPAs/complaints/NCRs/design changes between date A and B" → structured log query with counts, statuses, aging. (Never answer from embeddings; answer from the graph/log tables.)
3. **Single-thread walkthrough (multi-hop):** "For CAPA-2025-014: sources, root cause, actions, objective evidence, effectiveness check" → traverse hub edges, return each artifact + page cites.
4. **Trace-matrix walk:** "For requirement R / hazard H: show the full input→output→verification→validation / hazard→control→verification thread" → trace edges + rev-consistency check.
5. **As-of-date competence check:** "Was operator P trained on WI-x Rev-in-force when they signed DHR lot L, and was equipment E in calibration?" → temporal edge query.
6. **Reconciliation/diff:** "Complaint log vs. MDRs filed"; "ECO log vs. PMA supplements + annual report change lists"; "risk file occurrence estimates vs. actual complaint rates." → set differences across families; top 483 generators.
7. **Reverse traceability / blast radius:** "Gauge G found OOT on date D — what product did it accept since last good cal?" / "Supplier lot X was bad — which finished lots/consignees?" → genealogy traversal.
8. **Currency/completeness sweep:** "Which documents are past periodic review? Which validations/requalifications (sterilization, process) are overdue? Open CAPAs > 180 days?" → metadata aging queries.
9. **Risk-file feedback loop:** "Show that field data (complaints/MDRs/anomalies) re-entered the risk file per ISO 14971 Cl. 10" → post-production review records linked to hazard rows + rev history of RMF.
10. **Regulatory-consistency check:** "Is the device as built (DMR/DHR) consistent with the PMA manufacturing section / approved labeling?" → submission-to-source index traversal + rev comparison.

---

## 7. Ingestion Pipeline Implications (summary)

1. **Two-track ingestion:** every document flows through (a) metadata/ID/edge extraction into the graph and (b) chunk embedding — but families B/D (matrices, logs, DHRs, training, calibration) are graph-first, embedding-optional; families A/C (narratives, forms) are both.
2. **Chunk with structure, cite with page+section:** heading-based for class A; row-based with header context for class B; field+narrative for class C; step-based for class D. Audit answers must cite doc # + rev + section/page.
3. **Rev-awareness is non-negotiable:** all queries resolve against document *revisions* with as-of-date semantics; "current effective" is a filter, not the only view (auditors ask about the rev in force at event time).
4. **Master registers are ground truth:** ingest the doc register, item master, ASL, asset master, and DHF/DMR indexes first; use them to validate regex-extracted IDs before edge creation.
5. **OCR + confidence pipeline** for classes D/E with human-review queues; never present low-confidence extracted values as fact during a live audit — degrade to "located record, page N" with the image.
6. **Terminology bridging layer:** QSR↔ISO 13485↔QMSR synonym map (§ 1.1) applied at query time (auditor may say "DHF" or "design and development file"; "DMR" or "medical device file").
7. **Access/staging note:** during inspections, firms control what is produced; the system should tag content by producibility (e.g., pre-2026 practice treated internal audit *results* as not routinely provided to FDA — policy shifted under CP 7382.850; keep the flag configurable and legal-reviewed).

---

## 8. Sources (verified 2026-07-17)

- FDA — Quality Management System Regulation (QMSR): https://www.fda.gov/medical-devices/postmarket-requirements-devices/quality-management-system-regulation-qmsr and QMSR FAQ: https://www.fda.gov/medical-devices/quality-management-system-regulation-qmsr/quality-management-system-regulation-frequently-asked-questions
- Federal Register — QMSR Technical Amendments (Dec 2025): https://www.federalregister.gov/documents/2025/12/04/2025-21955/medical-devices-quality-management-system-regulation-technical-amendments
- Greenlight Guru — QMSR guide to new Part 820 (820.10/820.35/820.45): https://www.greenlight.guru/blog/qmsr-your-guide-to-part-820 ; BSI Compliance Navigator on new Part 820: https://compliancenavigator.bsigroup.com/en/medicaldeviceblog/the-new-fda-21-cfr-part-820--quality-management-system-regulation/
- Ropes & Gray — FDA's new inspection approach under QMSR (CP 7382.850): https://www.ropesgray.com/en/insights/alerts/2026/02/a-qmsr-state-of-mind-fda-adopts-new-inspection-approach-for-medical-devices ; The FDA Group — QMSR live / QSIT retired: https://www.thefdagroup.com/blog/qmsr-is-live-qsit-is-gone-a-guide-to-fdas-new-medical-device-framework ; qms.coach — CP 7382.850 six QMS Areas + four OAFRs: https://www.qms.coach/fda-compliance-program-7382-850-the-definitive-guide-to-medical-device-inspections-under-qmsr/
- FDA Town Hall — QMSR risk-based inspections (Apr 2026): https://www.fda.gov/medical-devices/medical-devices-news-and-events/town-hall-fdas-quality-management-system-regulation-qmsr-medical-device-risk-based-inspections
- eCFR — 21 CFR Part 803 (MDR): https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-803 ; FDA mandatory reporting: https://www.fda.gov/medical-devices/postmarket-requirements-devices/mandatory-reporting-requirements-manufacturers-importers-and-device-user-facilities
- eCFR — 21 CFR Part 812 (IDE) incl. 812.140/812.150: https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-812
- eCFR — 21 CFR Part 814 (PMA) incl. 814.20/814.39: https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-814 ; FDA PMA postapproval requirements (814.84): https://www.fda.gov/media/131249/download
- ISO 14971:2019 structure: https://www.iso.org/standard/72704.html ; RMF vs RMR explainer: https://meddeviceguide.com/blog/risk-management-file-vs-risk-management-report-iso-14971-documentation-guide ; Oriel STAT A MATRIX on 14971:2019: https://www.orielstat.com/blog/iso-14971-2019-revision/
- IEC 62304 classes/deliverables: https://www.greenlight.guru/blog/iec-62304-software-safety-classes ; https://blog.johner-institute.com/iec-62304-medical-software/safety-class-iec-62304/ ; https://www.ketryx.com/blog/a-comprehensive-guide-to-iec-62304-navigating-the-standard-for-medical-device-software ; SOUP: https://blog.johner-institute.com/iec-62304-medical-software/off-the-shelf-software-ots-versus-soup/
- QSIT background: https://www.mastercontrol.com/glossary-page/quality-system-inspection-technique/ ; https://aptskillmedtech.com/fda-qsit-inspections-what-to-expect-and-how-to-prepare-updated-for-qmsr-2026/

*Note: ISO/IEC standard clause numbers cited from the standards' publicly documented structure (ISO OBP and multiple corroborating secondary sources); the standards' full text is licensed and was not fetched. Where a claim rests only on secondary sources (e.g., internal-audit-report producibility under CP 7382.850), it is flagged inline.*

