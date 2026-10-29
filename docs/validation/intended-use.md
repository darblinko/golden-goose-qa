# Intended Use Statement

## Product

Golden Goose is a retrieval and question-answering assistant over a medical
device company's quality management system: controlled documents (SOPs, work
instructions, forms), quality records (CAPAs, complaints, NCRs, MDRs, audit
findings, training records, supplier records), design control artifacts
(requirements, verification and validation reports, trace matrices, FMEAs),
and selected external regulatory sources (openFDA, eCFR, ClinicalTrials.gov,
PubMed, web search).

## Intended use

Decision **support** during regulatory audit preparation and live audit
response: locating governing procedures, walking traceability from a
requirement to its verification evidence, retrieving the state and history of
quality records, and producing counts and summaries — each answer carrying
citations (document ID, revision, page) that the user verifies against the
controlled source before relying on it.

## Intended users

Quality, regulatory, and engineering staff of the operating company who are
trained on the QMS, authorized under its access-control policy, and able to
judge whether a cited source supports a claim. It is not for patients,
external auditors operating it directly, or users without QMS training.

## Environment

Deployed on company-controlled infrastructure (single Docker host in the
reference configuration). Authentication is required; access to records is
enforced per role by the ACL layer, and every turn is written to an
append-only, hash-chained audit log.

## Out of scope

- The system is **read-only** over quality records. It does not create,
  modify, approve, or close any QMS record, and has no write path to do so.
- It is not a medical device, does not perform diagnosis or treatment, and
  makes no clinical decisions.
- It does not replace the controlled document system as the source of truth.
  The controlled copy governs; an answer here is a pointer to it.
- Answers are not regulatory submissions or audit responses in themselves.
  A human formulates the response to the auditor; the assistant retrieves
  and cites.
- It is not a records-retention or e-signature system (not a 21 CFR Part 11
  electronic record/signature surface).

## Human oversight

Every answer streams its citations, and the verifier marks answers that lack
grounding. Users are required to open the cited document revision and confirm
the claim before acting on it. Ungrounded or uncited statements must be
treated as unverified.

## Data

Development and evaluation use an entirely synthetic QMS corpus
(`packages/synthdata`); no real patient, complaint, or device data is present
in this repository or its test suites.
