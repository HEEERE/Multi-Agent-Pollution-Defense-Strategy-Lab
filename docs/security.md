# Access Control and Secret Handling

## Local mode

When `MAJD_API_KEY` is empty, authentication is disabled for local offline
research. The backend should only be bound to trusted interfaces in this mode.

## Protected deployment

Set a strong server-side access key before exposing the service:

```text
MAJD_API_KEY=replace-with-a-random-secret
AUTH_SESSION_TTL_SECONDS=28800
```

All `/api/v1/*` endpoints then require either:

- `Authorization: Bearer <MAJD_API_KEY>` (automation and CLI clients), or
- the signed HttpOnly `majd_session` cookie issued by `POST /api/auth/session`.

The same cookie is checked during both WebSocket handshakes. Browser code never
reads or stores the server access key. Cookies use `SameSite=Strict`; deploy
behind TLS so the cookie is also marked `Secure`.

Rotating `MAJD_API_KEY` invalidates all existing signed sessions. `MIMO_API_KEY`
remains environment-only and is never accepted by or returned from the settings
API. Older SQLite `llm.api_key` rows are removed during startup.

## Current boundary

The access key represents one platform administrator role. Project-level RBAC,
tenant isolation, external identity providers, and per-user audit identities are
future productization layers; they are not implied by the current shared-key
authentication model.

## Persistent run queue

Strategy runs are stored as `queued` rows in SQLite. Workers atomically claim
the oldest job and execute the immutable strategy-version snapshot. Interrupted
`running` jobs return to `queued` on restart; user-cancelled jobs remain
`cancelled`. This removes dependence on process-local fire-and-forget tasks while
keeping the single-node deployment dependency-free.
