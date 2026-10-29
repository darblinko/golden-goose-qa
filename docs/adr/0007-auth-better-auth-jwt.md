# ADR 0007: Library auth (Better Auth) + JWT validation, not Keycloak

Status: accepted (2026-07-17)

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
