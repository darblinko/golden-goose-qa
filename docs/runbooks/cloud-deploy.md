# Cloud Deployment Runbook

How to take the compose-based system to AWS or Azure using the Terraform
skeletons in `infra/terraform/`. The skeletons are validated configurations
(`terraform validate` clean), not turnkey production stacks — the gaps and
their order of attack are listed at the end.

## Images

`.github/workflows/images.yml` builds and publishes both images to GHCR on
every push to main and on version tags:

- `ghcr.io/<owner>/<repo>-api` — API and worker (same image; the worker runs
  `saq gg_ingestion.worker.settings`)
- `ghcr.io/<owner>/<repo>-web` — Next.js UI

`NEXT_PUBLIC_API_URL` is baked into the web bundle at build time
(`Dockerfile.web` build arg). The AWS stack serves one origin — the ALB routes
`/api/*` to the API and everything else to the web app — so build the web image
with a **relative** API base:

```bash
docker build -f Dockerfile.web --build-arg NEXT_PUBLIC_API_URL=/api -t <tag> .
```

The bundle then calls `/api/...` on whatever host serves it, so the same image
works behind HTTP or HTTPS and needs no rebuild when the domain changes. Only a
split-origin deployment (API on a separate hostname) needs an absolute
`https://<api endpoint>` here.

## AWS (`infra/terraform/aws`)

Stands up: VPC with two public subnets, RDS Postgres (engine major version 18),
three S3 buckets (documents, artifacts, backups), SSM SecureString secrets, an
ECS Fargate cluster running api/worker/web behind a single ALB, and a Cognito
user pool. The ALB is one origin: a `/api/*` listener rule forwards to the API
target group (port 8000, health check `/api/health`); the default action serves
the web app (port 3000). There is no separate `:8080` API listener — the API is
reached only through `/api/*` on the same port the browser already uses.

```bash
cd infra/terraform/aws
terraform init
terraform apply \
  -var api_image=ghcr.io/<owner>/<repo>-api:<tag> \
  -var web_image=ghcr.io/<owner>/<repo>-web:<tag> \
  -var qdrant_url=https://<cluster>.cloud.qdrant.io \
  -var neo4j_uri=neo4j+s://<id>.databases.neo4j.io
# sensitive vars (db_admin_password, db_app_password, jwt_secret,
# neo4j_password, anthropic_api_key, voyage_api_key, google_api_key, and
# qdrant_api_key when using Qdrant Cloud) via TF_VAR_* env or a gitignored *.tfvars file — never on
# the command line in shared shells
```

The API service sets `GG_API_ROOT_PATH=/api` (services.tf) so every route is
registered under that prefix; the value is inert for the worker, which shares
the env block but serves no HTTP.

TLS is opt-in. Pass `-var acm_certificate_arn=arn:aws:acm:...` and the ALB adds
a 443 HTTPS listener (TLS 1.2+ policy) and redirects :80 → :443; the `/api/*`
rule moves to the HTTPS listener automatically. Without the variable the ALB
serves plain HTTP — acceptable only for a closed, disposable test deploy.

Qdrant and Neo4j are consumed as managed endpoints (Qdrant Cloud, Aura) per
the cloud map in the architecture doc; the skeleton does not run them as
containers.

After apply, bootstrap the database once (any host that can reach RDS —
tasks run in public subnets, so a one-off ECS task or a temporary bastion):

The api and worker tasks receive no admin credential. Migrations are the only
step that uses gg_admin; export `GG_PG_ADMIN_PASSWORD` (the db_admin_password
value) in the shell that runs them. With `GG_ENVIRONMENT` set to dev or prod,
the migration environment refuses to run on the shipped development admin
password.

```bash
# as gg_admin:
uv run alembic -c infra/migrations/alembic.ini upgrade head
uv run gg-ingest graph-migrate
# then set the gg_app role password to the db_app_password value
```

Acceptance is the same bar as local: ingest a corpus, then
`uv run gg-eval battery --qa ... --smoke` pointed at the cloud fleet
(GG_PG_HOST, GG_QDRANT_URL, GG_NEO4J_URI, GG_S3_* from Terraform outputs)
must clear all gates.

State starts local so one operator can stand the stack up with no
prerequisites. Before any shared or repeated use, move it to S3 — the backend
block is stubbed in `versions.tf` and the one-time bootstrap is in
`infra/terraform/aws/REMOTE_STATE.md`.

### Teardown

`scripts/teardown_aws.sh` destroys the whole application stack under the AWS
profile named in `AWS_PROFILE`. Terraform cannot delete a
non-empty versioned S3 bucket, so the script empties every bucket's versions
and delete-markers first, clears RDS deletion protection, runs
`terraform destroy -auto-approve`, then confirms zero resources remain via the
`project` tag. It prompts before destroying unless `FORCE=1`.

```bash
AWS_PROFILE=<profile> scripts/teardown_aws.sh
```

It does not remove the remote-state bucket (see REMOTE_STATE.md) and cannot see
untagged global resources (IAM, Cognito domains) — those are reported, not
deleted.

## Azure (`infra/terraform/azure`)

Stands up: resource group, PG Flexible Server (version 17), a storage account
with the three containers, a Container Apps environment running api/worker/web,
and an Entra ID app registration. Same variable surface and the same bootstrap
and acceptance procedure as AWS, plus `s3_gateway_endpoint_url`,
`s3_gateway_access_key` and `s3_gateway_secret_key` for the S3 gateway described
below.

Postgres version deviates by cloud: AWS RDS pins engine major 18, Azure
Flexible Server pins 17 (the newest major the two managed services each offer at
the time of writing). Both are within the range the schema and migrations
support; keep them on the newest each provider exposes rather than forcing a
match.

Azure-specific gap: Blob has no native S3 API. Until the ObjectStore seam
gets a native blob adapter (or an S3 gateway is deployed in front of Blob),
the api/worker apps cannot reach documents — this is the one seam that is
code, not configuration, on Azure (ADR 0020).

## Known gaps before production use

1. TLS: wired on AWS but off by default — supply `acm_certificate_arn` to turn
   on the 443 listener and the :80 → :443 redirect (see above). Azure still
   needs a custom domain + managed cert on Container Apps.
2. Private networking: Fargate tasks and RDS still run in public subnets; move
   them to private subnets behind a NAT, VNet-integrate Flexible Server, and
   drop the service firewall rule.
3. Auth swap: validate Cognito/Entra OIDC tokens instead of app-issued
   HS256 JWTs (ADR 0020); until then cloud auth still uses GG_AUTH_JWT_SECRET.
4. Terraform remote state: the S3 backend block and bootstrap are ready
   (`versions.tf` stub + `REMOTE_STATE.md`) but not yet migrated — state is
   still local until an operator runs the one-time bootstrap.
5. Scheduled `gg-backup` runs against cloud stores, writing to the backups
   bucket/container.
6. Phoenix/LangSmith wiring via GG_TRACING_* to a reachable collector.
