# ADR 0007: Library auth (Better Auth) + JWT validation, not Keycloak

Status: accepted (2026-07-17); not implemented. See "Implementation status" below.

## Context
Multi-user (audit backroom, prep team, daily QA/RA) needs sessions, roles, and
a stable user identity for the audit trail. An IdP container (Keycloak) costs
~1 GB RAM and heavy configuration for a handful of users; enterprises will
bring their own IdP anyway.

## Decision
Better Auth in the Next.js app owns signup/session/roles and issues JWTs
(EdDSA, JWKS endpoint). FastAPI validates JWTs statelessly (PyJWT), keying
users as (issuer, subject) so a future enterprise IdP (Entra ID, Okta) is an
additive issuer, not a migration.

## Consequences
- No IdP container in the fleet; auth state lives in Postgres `app` schema.
- The audit log's `actor` is the JWT (issuer, subject) — stable across auth
  backends.
- SSO later = configure a second trusted issuer.

## Implementation status

The Better Auth part of this decision is not implemented. What the code does:

- The API validates HS256 JWTs signed with one shared secret
  (`apps/api/src/goldengoose_api/auth.py`). It requires `sub`, `exp`, `iss`,
  `aud` and `role`, and checks the configured issuer and audience. There is no
  EdDSA signing and no JWKS endpoint.
- The only token source is `POST /auth/dev-token`, which mints a token for any
  email and role. The route is registered only when the environment is `local`
  or `ci` (`apps/api/src/goldengoose_api/main.py`). The web app signs in through
  it (`apps/web/lib/api.ts`).
- There is no signup, password, session store or role administration. The
  audit log `actor` is the token subject alone, not (issuer, subject).

A deployment outside `local` or `ci` therefore has no way to sign in until an
identity provider issues tokens the API accepts.
