# ADR 0005: SeaweedFS replaces MinIO for local object storage

Status: accepted (2026-07-17)

## Context
The original hypothesis was MinIO, but MinIO's open-source repository was
archived in April 2026 and its community edition gutted before that. We need
an S3-compatible local store that remains maintained, with a clean path to
real S3/Azure Blob in cloud deployments.

## Decision
SeaweedFS 4.x (`chrislusf/seaweedfs:4.39`, single-binary `weed server -s3`)
provides the local S3 endpoint. All application code talks to the
`ObjectStore` seam (boto3 S3 implementation + local-filesystem test fake);
nothing imports SeaweedFS specifics.

## Consequences
- Cloud migration is a settings change (endpoint/credentials), zero code.
- SeaweedFS runs in ~512 MB, well under MinIO's footprint.
- Bucket layout: `gg-documents` (originals, content-addressed), `gg-artifacts`
  (parsed intermediates, OCR output, eval reports).
