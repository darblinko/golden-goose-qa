# ADR 0011: Native format parsers for M1; Docling deferred to Phase 4

Status: accepted (2026-07-18)

## Context
The M1 corpus is machine-generated and format-clean: DOCX with real heading
styles, XLSX with typed cells, CSV, Markdown, and digital PDFs. Docling
brings layout analysis, table structure recovery, and OCR — capabilities that
matter for scanned and messy real-world documents but add a heavy model
download, slower cold starts, and a larger image for no M1 benefit.

## Decision
M1 ingestion parses each format natively: python-docx for DOCX, openpyxl for
XLSX, pypdf for digital PDFs, stdlib csv, plain text/Markdown directly.
Scanned PDFs (no extractable text layer) are classified `skipped_unsupported`
and recorded in the registry rather than mis-ingested. Docling (with OCR)
enters in Phase 4 behind the same `Parser` interface, keyed off the existing
format-detection step, so the pipeline contract does not change.

## Consequences
- The M1 image stays small and ingestion is fast and deterministic.
- Five corpus files (3 scanned DHR PDFs, TRN-100, ASL-100) are deliberately
  deferred; the integration test pins that count so silent regressions in
  format detection fail CI.
  - Update (2026-07-18): Phase 3 added native parsers for TRN-100 (xlsx
    training grid) and ASL-100 (supplier list matrix), so only the 3 scanned
    DHR PDFs remain deferred to the Docling/OCR path.
- Provenance granularity (page/bbox) for scanned documents arrives only with
  Docling; the citation schema already carries `page` so no migration is
  needed then.
