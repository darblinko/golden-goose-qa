# ADR 0020: Cloud extensibility as validated skeletons, not a performed deployment

Status: accepted (2026-07-18)

## Context
Phase 7's plan called for Terraform skeletons for AWS and Azure exercising
the adapter seams, an image-publish CI job, and — as acceptance — a dev
deploy to one cloud with the eval smoke green. This development environment
has no cloud account or credentials, and creating one is an organizational
decision (billing, tenancy, data policy) that should not be made
unilaterally by the build process.

## Decision
- Ship validated Terraform skeletons (`infra/terraform/aws`,
  `infra/terraform/azure`) — `terraform validate` clean against pinned
  providers (aws ~> 6.0, azurerm ~> 4.0, azuread ~> 3.0), with provider
  lock files committed. AWS: ECS Fargate + RDS + S3 + SSM secrets + Cognito
  behind an ALB. Azure: Container Apps + PG Flexible Server + Blob + Entra
  app registration. Qdrant and Neo4j are consumed as managed endpoints
  (Qdrant Cloud, Aura) per the architecture cloud map, not self-run.
- Ship the image CI (`.github/workflows/images.yml`): GHCR publish of the
  api and web images on main and version tags, build-only on PRs, using
  only the repository's own GITHUB_TOKEN — no external registry secrets.
- Record the acceptance deviation explicitly: the actual cloud deploy and
  cloud-side eval smoke are NOT performed. The runbook
  (`docs/runbooks/cloud-deploy.md`) defines that acceptance step so the
  first operator with an account executes exactly it.
- Seam status: Postgres and S3 are configuration-only swaps (the object
  store now falls back to the SDK credential chain when endpoint/key are
  unset). Auth is provisioned (Cognito pool / Entra registration) but token
  validation still uses app-issued HS256 JWTs — the OIDC swap is
  application work. Azure Blob needs a native ObjectStore adapter or an S3
  gateway; it is the one seam that is code rather than configuration.

## Consequences
- Phase 7 delivers everything reproducible without an account, and nothing
  that pretends a deployment happened.
- The skeletons cannot have drifted-from-reality bugs a real apply would
  catch (IAM subtleties, quota, AZ capacity); first apply will surface
  those, which is why the runbook keeps the bootstrap and acceptance steps
  next to the Terraform.
- Cost posture stays honest: nothing in CI or nightly runs touches a cloud
  provider or can accrue charges.
