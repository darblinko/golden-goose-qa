# Requirements Traceability

Requirements → implementation → verification. Verification names the **exact
test function(s)** that exercise the requirement, so a reviewer can resolve and
read each one rather than trust a filename. The **Coverage** column states how
that evidence is produced and how far it reaches:

- **CI-unit** — pure unit test; runs on every CI push (no live services).
- **CI-integ** — integration test against live Postgres/Qdrant/Neo4j in CI
  (fixtures `ingested_corpus` / `derived_corpus` / `app_engine`); not runnable
  in a keyless dev sandbox.
- **Nightly** — gate enforced by the nightly eval battery over the golden QA
  set (`gg-eval battery`).
- **Manual** — run per release by an operator; the run's artifact (stdout/JSON
  or uploaded bundle) is the evidence and must be attached with SHA/date/result.

A filename alone is not proof a requirement passed; the semantic-coverage notes
under the table record, per row, *what the cited test actually asserts* and any
boundary it does not reach.

| ID | Requirement | Implementation | Verification (exact test IDs) | Coverage |
| --- | --- | --- | --- | --- |
| R-01 | Answers cite document ID and revision for every retrieved-text claim, with page for PDF sources; graph and register answers cite the document IDs the tool read | Parent-child retrieval carries doc metadata into generation; citation extraction in `gg_agents.nodes` | `packages/agents/tests/test_graph.py::test_happy_path_is_grounded_and_cited`; e2e `tests/integration/test_agent_acceptance.py::test_complaint_risk_gap_finds_seeded_complaint`; citation precision/recall gated nightly | CI-unit + CI-integ + Nightly |
| R-02 | Ungrounded answers are flagged before display | Verifier node assigns a verdict per turn; SSE `done` carries it | `packages/agents/tests/test_graph.py::test_empty_retrieval_rewrites_twice_then_answers_honestly`; nightly grounded-rate gate ≥ 0.8 | CI-unit + Nightly |
| R-03 | Retrieval quality floor over the golden QA set | Hybrid dense+sparse retrieval with rerank (`gg_retrieval`) | `tests/integration/test_retrieval_pipeline.py::test_ingest_retrieve_eval_end_to_end`; nightly recall@10 gate ≥ 0.8 | CI-integ + Nightly |
| R-04 | Unambiguous questions route deterministically to the right tool | `gg_agents.toolselect` regex layer ahead of the LLM router (ADR 0016) | `packages/agents/tests/test_toolselect.py` (full class); nightly routing-accuracy gate ≥ 0.9 | CI-unit + Nightly |
| R-05 | Reranking is robust to near-duplicate distractors | Cross-encoder rerank stage in `gg_retrieval.retriever` | `packages/evals/tests/test_noise.py::test_evaluate_noise_with_fake_reranker`, `::test_untested_items_do_not_score_as_perfect_robustness`; nightly noise-degradation gate (mean recall@10 lost to distractors) ≤ 0.15 | CI-unit + Nightly |
| R-06 | Read-only over quality records; no write path to QMS data | Agent tools expose only SELECT-shaped warehouse queries (`gg_retrieval.sqlguard`, ADR 0015) and read graph walks | `packages/retrieval/tests/test_sqlguard.py` (full suite: SELECT-only, CTE/UNION/join allow, mutations rejected) | CI-unit |
| R-07 | Access to records enforced per role | ACL layer (`gg_common.acl`) applied in retrieval and record tools | `packages/common/tests/test_acl.py::test_auditor_cannot`; `tests/integration/test_acl_enforcement.py::test_retrieval_filter_blocks_restricted_chunks`, `::test_rls_backstop_blocks_rows_without_the_flag` | CI-unit + CI-integ |
| R-08 | Every turn recorded in an append-only, tamper-evident audit log | Hash-chained audit log (ADR 0010) written per turn; DB-level UPDATE/DELETE/TRUNCATE denial | `tests/integration/test_audit_immutability.py::test_chain_verifies_after_inserts`, `::test_update_rejected_even_for_admin`, `::test_truncate_rejected_even_for_admin`; `tests/integration/test_audit_report.py::test_report_reproduces_every_seeded_defect` | CI-integ |
| R-09 | Authentication required; no anonymous access outside dev tokens | JWT auth (ADR 0007); dev-token mint restricted by environment | `tests/integration/test_chat_api.py::test_chat_turn_streams_and_persists` (owner isolation: other owner gets 404) | CI-integ |
| R-10 | Authoritative data restorable after loss | `gg-backup` create/restore with sha256 manifest (ADR 0018) | `tests/integration/test_backup_restore.py::test_backup_restore_drill` | CI-integ + Manual runbook |
| R-11 | Fleet operates within the single-host memory budget under concurrent chat + ingestion load | Compose per-service memory limits; host-process (API + derive) PID-subtree sampling | `scripts/load_sanity.py` (per-release run); helper logic `tests/test_load_sanity_helpers.py::test_missing_members_flags_absent_container_and_process`, `::test_fleet_budget_alert_triggers_only_over_budget` | Manual + CI-unit (helpers) |
| R-12 | System functions without provider keys, deterministically | Fake providers (ADR 0009) selected automatically when keys are absent | Entire unit + integration suite runs keyless in CI; `packages/common/tests/test_costs.py::test_fake_providers_record_estimated_usage` | CI-unit + CI-integ |
| R-13 | External tools cannot be silently exercised during evals | `run_battery` calls `force_offline` before building the toolkit | `packages/evals/tests/test_battery_gates.py::test_force_offline_disables_live_external_tools`; `tests/integration/test_eval_battery.py::test_smoke_battery_clears_all_gates` | CI-unit + CI-integ |
| R-14 | Dependency licenses restricted to permissive/weak-copyleft; known vulns surface in CI | `scripts/license_audit.py` (SPDX-expression parsing); pip-audit + npm audit in CI | `tests/test_license_audit.py::test_and_expression_requires_every_term_allowed`, `::test_environment_audit_passes_here`, `::test_real_npm_lockfile_passes`; CI `audit` job | CI-unit + CI |
| R-15 | Quality trend visible over time | Battery history JSONL + self-contained HTML dashboard; nightly artifact upload | `packages/evals/tests/test_history_dashboard.py::test_history_roundtrip`, `::test_prune_incomparable_drops_records_from_a_different_schema`; workflow `.github/workflows/nightly-eval.yml` uploads `eval-trends/` | CI-unit + Nightly artifact |
| R-16 | Per-turn cost and latency observable **in-band** (not persisted; ADR-0017 scope) | Cost ledger + tracing seam (ADR 0017); turn total emitted on SSE `done`, log line, span | `packages/common/tests/test_costs.py::test_ledger_aggregates_by_stage`, `::test_unknown_model_costs_zero_but_tokens_count`; `packages/common/tests/test_tracing.py::test_spans_nest_and_export`; e2e emission `tests/integration/test_chat_api.py::test_chat_turn_streams_and_persists` | CI-unit + CI-integ |
| R-17 | Superseded document revisions never answer as current | Retrieval filters to effective revisions by default (`gg_retrieval.search.build_filter`); ingestion supersede planning | `packages/retrieval/tests/test_retriever.py::test_status_filter_applied_by_default`; `packages/retrieval/tests/test_search.py::test_status_only`, `::test_as_of_bounds_controlled_effective_window`; `packages/ingestion/tests/test_supersede.py::test_older_revision_becomes_obsolete_closed_at_successor`; e2e `tests/integration/test_retrieval_pipeline.py::test_as_of_returns_the_revision_effective_on_that_date` | CI-unit + CI-integ |
| R-18 | Operator can run, back up, evaluate, and diagnose from documented procedures | Runbooks | `docs/runbooks/operator-runbook.md`, `docs/runbooks/backup-restore.md` (manual review) | Manual |

## Semantic-coverage notes

Per-row notes on what the cited tests assert and the boundary each does not
reach:

- **R-10** — `test_backup_restore_drill` restores into a fresh store and then
  calls `_audit_chain_intact()`, asserting the restored audit log's sha256
  hash-chain validates end to end (`chain_ok and checked > 0`). This closes the
  earlier gap where the drill reloaded rows but never re-verified the chain.
  Boundary: the runbook procedure itself (`backup-restore.md`) is a manual step;
  the automated drill bypasses the compose-profile restore command, so a
  fresh-volume disaster restore from the runbook alone is still a manual check.
- **R-11** — no baked-in run result is claimed here. The gate lives in
  `load_sanity.py` and now fails closed when any required fleet member (the four
  core containers, the API process, and derive unless skipped) is never
  observed, when any container exceeds its per-limit alert fraction, or when the
  summed fleet peak exceeds the 10 GiB single-host budget. Each release run must
  attach its stdout as the artifact (date + git SHA + pass/fail); the pure
  helpers are unit-tested so the gate logic itself is trustworthy.
- **R-13** — the offline invariant is no longer inferred from a gate test. It is
  extracted into the pure `force_offline` and asserted directly: even with
  external tools online in settings, the battery forces `offline=True` without
  disturbing other external settings and without mutating the original.
- **R-15** — every nightly run uploads its `report.json` / `dashboard.html`
  bundle as a build artifact (`if: always()`, `if-no-files-found: error`), so
  per-run evidence is immutable. Boundary: long-run trend *continuity* depends
  on the GitHub Actions cache keyed by `github.run_id` (immutable per run) with a
  prefix `restore-keys`; under concurrent runs the history can fork, a rerun
  cannot append to an existing run's key, and cache eviction resets the series.
  Treat the continuous-looking trend line as best-effort, not a guaranteed
  unbroken record.
- **R-16** — scope corrected to match ADR-0017: per-turn cost/latency are
  observable **in-band** (SSE `done` payload, structured log, span) on the
  successful chat path, which the integration test now asserts
  (`{"cost_usd","input_tokens","output_tokens"} <= usage`). The seam unit tests
  prove ledger aggregation (including unknown-model = $0-but-tokens-count) and
  span export. **Not covered / out of scope:** persistence to a cost column,
  cross-conversation SQL aggregation, failed-turn accounting, and worker cost —
  ADR-0017 explicitly defers these.
- **R-17** — retrieval filtering is now the primary evidence, not the supersede
  planner alone. `test_status_filter_applied_by_default` proves the retriever
  applies the current-only status filter unless an as-of date is supplied;
  `test_as_of_bounds_controlled_effective_window` proves the as-of path; the
  ingestion `test_supersede.py` cases prove revisions are marked obsolete at
  their successor. The end-to-end `test_as_of_returns_the_revision_effective_on_that_date`
  ties both halves together against live services.

## Sign-off

This matrix is auditor-facing objective evidence. Before the validation package
is marked reviewed:

1. An independent reviewer (not the author of the change under review) must
   resolve every cited `file::test_function` ID and confirm it asserts the
   mapped requirement, not merely that the file exists.
2. For **Manual** rows (R-10 runbook, R-11, R-18), the reviewer must record the
   run's git SHA, date, and pass/fail result, and attach the run artifact.
3. CI-integ and Nightly rows must show a green run at the reviewed SHA; a
   filename with no corresponding passing run does not count as verified.

Calibrated gate values and the rationale for the lexical support metric are in
ADR 0019. Accepted scope boundaries are in
`docs/validation/known-limitations.md`. The intended-use boundary this matrix
serves is `docs/validation/intended-use.md`.
