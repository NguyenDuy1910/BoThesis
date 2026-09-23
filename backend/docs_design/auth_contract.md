# Authentication API Contract

Status: target contract. This document is part of the contract-first gate;
implementation changes wait until this model is accepted.

## Resource model

Authentication mechanisms create one durable `Session`. Mechanism names do not
become URL namespaces.

| Method | Path | Security | Resource operation |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/accounts` | public | Create Account and issue first Session |
| POST | `/api/v1/auth/sessions` | public | Create Session from typed method variant |
| GET | `/api/v1/auth/session` | bearer | Read current Session context |
| PATCH | `/api/v1/auth/session` | bearer | Change active workspace state |
| DELETE | `/api/v1/auth/session` | bearer | Invalidate current Session |

No `/auth/password`, `/auth/google`, or `/auth/guest-sessions` routes remain in
the final contract. No password reset routes are added because current product
has no recovery lifecycle.

## Account creation

`POST /api/v1/auth/accounts` accepts:

```json
{
  "email": "user@example.com",
  "password": "...",
  "username": "analyst",
  "display_name": "Example User"
}
```

`email` is the canonical local credential identifier for account creation.
Password sign-in accepts either the account email or the optional username;
exactly one identifier is required. Account creation returns `201` and the
same `AuthSession` shape as login. `409` uses `ACCOUNT_ALREADY_EXISTS`; `422` uses
`VALIDATION_ERROR`.

## Session creation

`POST /api/v1/auth/sessions` uses `CreateSessionRequest`, a discriminated
`oneOf` union with `method`:

```json
{ "method": "password", "email": "user@example.com", "password": "..." }
```

Username sign-in is also supported for accounts that have one:

```json
{ "method": "password", "username": "analyst", "password": "..." }
```

```json
{ "method": "guest" }
```

```json
{ "method": "google", "credential": "provider-issued-token" }
```

Each variant has a closed, concrete schema. No arbitrary `credentials` map is
accepted. Future OIDC providers add a typed variant and provider strategy
behind this route; they do not add a provider-specific route.

All variants return `AuthSession`. Password and provider failures return generic
`401 INVALID_CREDENTIALS` without revealing whether account or credential was
wrong. Guest creation uses the same durable access-session abstraction and may
have a shorter expiration and restricted permissions, represented by
`session_kind: "guest"`.

## Current session lifecycle

`GET /auth/session` resolves identity from the bearer token and returns
`CurrentSession`. It never accepts `user_id`, `workspace_id`, roles, or
permissions from the caller.

`PATCH /auth/session` accepts only:

```json
{ "active_workspace_id": "uuid" }
```

Server validates workspace membership/public access, creates the replacement
session context, and returns `AuthSession`. Internal `tenant_id` and JWT claim
`active_tenant_id` stay behind the API boundary.

`DELETE /auth/session` resolves the bearer session and tombstones/revokes it;
response is `204`. No physical business data is deleted.

## OpenAPI and error rules

- Global OpenAPI security is bearer JWT.
- Account/session creation explicitly uses `security: []`.
- Current-session GET/PATCH/DELETE require bearer security.
- Auth errors use shared `{code, message, request_id, details}` envelope.
- Stable auth codes: `INVALID_CREDENTIALS`, `SESSION_EXPIRED`,
  `ACCOUNT_ALREADY_EXISTS`, `ACCOUNT_DISABLED`, `TOO_MANY_ATTEMPTS`.

## Migration/deletion gate

Implementation may begin after `openapi.yaml` matches this model. Completion
requires removing public routes, DTOs, operation IDs, frontend methods, and
tests for provider-shaped login endpoints. Internal authenticator strategy
methods may remain only behind `SessionService`; they must not be exported as
HTTP aliases.

## Local full-access test accounts

`backend/script/seed_account.py` is an idempotent local-development utility,
not an HTTP API. It synchronizes platform-defined roles, creates the three
`admin{1,2,3}@bothesis.local` accounts when absent, grants each
`platform_admin`, and grants each active workspace membership plus
`tenant_admin`. This combines platform administration with workspace data
access without weakening the normal separation of those scopes.

New accounts use `ChangeMe!123` unless `--password` is provided. Re-running
the script preserves existing passwords; `--reset-password` is required to
change them. If no active workspace exists, it creates `sample-workspace` so
the accounts can establish an active authenticated workspace.

The complete local reset command, `make reset-all`, runs this seeder after
database initialization.
