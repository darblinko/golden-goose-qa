# ADR 0001: uv workspace monorepo on Python 3.13

Status: accepted (2026-07-17)

## Context
The platform has several deployable units (api, worker) and shared libraries
(common, ingestion, retrieval, agents, synthdata) that must version together
during rapid build-out, with one lockfile as the single dependency truth.

## Decision
One uv workspace at the repo root; every package is a workspace member with
hatchling builds. Python is pinned to 3.13 (`>=3.13,<3.14`). `uv.lock` is
committed and CI installs with `--locked`.

## Consequences
- One `uv sync` bootstraps everything; drift between packages is impossible.
- Docker builds layer dependency install (`--no-install-workspace`) before
  source copy for fast rebuilds.
- Python 3.14+ upgrades are an explicit, tested decision, not an accident.
