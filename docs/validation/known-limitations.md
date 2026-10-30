# Known limitations accepted at the current scope

Design decisions that are **accepted at the current scope** rather than
treated as defects. Each entry records what the limitation is, why it is
acceptable now, what would trigger revisiting it, and where the behavior lives
in code or an ADR. This document is the scope companion to
[intended-use.md](./intended-use.md) and
[requirements-traceability.md](./requirements-traceability.md).

The items below are scope or maturity boundaries. None of them is a path by
which the system produces a wrong or unsafe answer.

## `auditor_readonly` can create and delete its own chat threads

- **What:** The `auditor_readonly` role (external auditor; can read only
  general-access content, never restricted — see `packages/common/src/gg_common/acl.py`)
  is not blocked from creating or deleting threads.
- **Why acceptable:** Threads are the user's own scratch workspace, not QMS
  records. Deleting a thread destroys no audit-relevant artifact: the audit log
  is a separate append-only table ([ADR-0010](../adr/0010-append-only-audit-log.md))
  that thread deletion does not touch. Read isolation, which
  is the property that matters for this role, is enforced and tested
  (`packages/common/tests/test_acl.py`).
- **Revisit when:** Threads become retained records, or auditor sessions must be
  preserved for the audit itself.

## Rate limiting is in-process, single-instance

- **What:** `apps/api/src/goldengoose_api/ratelimit.py` is a fixed-window
  limiter backed by an in-memory dict; counts are per process and reset on
  restart.
- **Why acceptable:** The current deployment is a single API process. The
  module's own docstring records the boundary.
- **Revisit when:** The API scales horizontally — then the window must move to a
  shared store (Redis or Postgres) so limits are enforced across instances.

## Auth is a local dev token; Better Auth, OIDC and cookie tokens are not implemented

- **What:** [ADR-0007](../adr/0007-auth-better-auth-jwt.md) chose Better Auth
  with EdDSA JWTs and a JWKS endpoint. None of that is built. The API validates
  HS256 JWTs signed with a shared secret, and the browser gets its token from
  `POST /auth/dev-token`, which accepts any email and role. That route exists
  only when the environment is `local` or `ci`. There is no signup, session
  store, role administration, OIDC federation or httpOnly-cookie transport; the
  token is held by the browser client.
- **Why acceptable:** The project runs as a local and CI demonstration.
  Requests without a valid token are rejected (`tests/unit/test_api_auth.py`),
  and the dev-token route is absent outside `local` and `ci`.
- **Consequence:** A deployment in any other environment cannot sign users in.
  Role claims from the dev token are self-asserted, so role-based access is a
  demonstration of enforcement, not of identity proofing.
- **Revisit when:** The application is deployed for real users; an identity
  provider must then issue the tokens and the browser token storage must be
  threat-modeled for XSS token theft.

## Eval battery uses hand-rolled metrics, not DeepEval / RAGAS

- **What:** The named third-party eval frameworks (DeepEval, RAGAS) are absent;
  the dashboard and NoiseSensitivity-style checks are local implementations,
  authorized by [ADR-0019](../adr/0019-eval-battery-lexical-gates.md).
- **Why acceptable:** The substitution itself is an explicit ADR decision.
  Citation entailment is checked by a local implementation
  (`packages/evals/src/gg_evals/entailment.py`) with adversarial tests
  (`packages/evals/tests/test_entailment.py`); the framework choice does not
  change answer correctness.
- **Revisit when:** A regulator or downstream consumer requires a named,
  externally recognized eval framework, or the hand-rolled metrics stop keeping
  pace with the checks we need.

## Graph label set is deliberately narrow (7 node labels), no Text2Cypher

- **What:** The knowledge graph defines 7 node labels — `Document`,
  `DocumentRevision`, `Requirement`, `DesignOutput`, `Supplier`, `Person`,
  `FmeaRow` (`NODE_KEY_PROPERTY` in
  `packages/ingestion/src/gg_ingestion/extract/model.py`) with a fixed
  relationship vocabulary — not the broader ~37-label taxonomy an early design
  sketch imagined. Natural-language Text2Cypher is not present in the code.
- **Why acceptable:** The shipped labels are the ones the current corpus and
  retrieval paths actually use; graph queries run through vetted saved traversals
  (`packages/retrieval/src/gg_retrieval/tools/graph_walk.py`), never
  LLM-generated Cypher, which is the safer posture. The speculative extra labels
  and the Text2Cypher path were removed rather than left as dead code, so the
  documentation now matches the implementation.
- **Revisit when:** New document types need first-class graph entities, or a
  genuine need for open-ended graph querying outweighs the safety of a fixed,
  reviewed query set.
