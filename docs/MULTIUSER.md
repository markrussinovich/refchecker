# Multi-User & Teams Setup

RefChecker runs **single-user/local by default** — no login, no team, no presence,
every request runs as a built-in local admin. Multi-user mode is **opt-in**: it
turns on only when you set `REFCHECKER_MULTIUSER=true` **and** configure at least
one OAuth provider's client ID + secret (Google, GitHub, or Microsoft). Setting the
flag alone — with no provider credentials — leaves the app in single-user mode and
shows no login screen.

Once at least one provider is configured, the Web UI gates behind a login page that
shows a sign-in button **only** for providers the server reports at
`/api/auth/providers`, and every API route requires a valid session. The **CLI is
unaffected** — `academic-refchecker` and `refchecker-webui check` work without any
auth configuration and never make a team/collaboration claim.

There are two ways to enable multi-user mode:

- **From inside the app** (no env editing, hot-reload) — recommended for the
  desktop app and local servers.
- **Via environment variables** — recommended for hosted/server deployments.

---

## Option A — Enable accounts & Teams from inside the app (hot-reload)

Settings has a real **Accounts & Teams** form. Flip on multi-user mode, paste your
Google / GitHub / Microsoft OAuth credentials, and **Apply**. The app:

1. Persists the config to a private app-data file (`auth_config.env`) — secrets are
   **write-only**: omitted/blank fields are kept as-is and are **never echoed back**.
2. **Hot-reloads** the saved config into the running process via
   `PUT /api/auth/config` → `reload_config(...)`, so accounts / Teams / presence
   light up without a manual restart (the desktop app relaunches the sidecar to
   apply cleanly).

What the form maps to (handled by the backend, you don't set these by hand here):

| Form field | Saved key |
|---|---|
| Enable multi-user | `REFCHECKER_MULTIUSER=true/false` |
| Google client ID / secret | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` |
| GitHub client ID / secret | `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` |
| Microsoft client ID / secret | `MS_CLIENT_ID` / `MS_CLIENT_SECRET` |

In multi-user mode, changing this config is **admin-only**. A provider only becomes
a usable login button when **both** its ID and secret are present.

---

## Option B — Enable via environment variables (servers)

### 1. Generate a JWT secret

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Register an OAuth application (at least one)

| Provider | Registration | Callback URL |
|---|---|---|
| **Google** | [Google Cloud Console](https://console.cloud.google.com/apis/credentials) | `https://<domain>/api/auth/callback/google` |
| **GitHub** | [GitHub Developer Settings](https://github.com/settings/developers) | `https://<domain>/api/auth/callback/github` |
| **Microsoft** | [Azure App Registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps) | `https://<domain>/api/auth/callback/microsoft` |

### 3. Configure environment variables

```ini
REFCHECKER_MULTIUSER=true
JWT_SECRET_KEY=<output from step 1>
SITE_URL=https://<your-domain>
HTTPS_ONLY=true

# At least one provider — only providers whose ID *and* secret are set
# appear as login buttons. Microsoft uses the MS_* prefix.
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...

MS_CLIENT_ID=...
MS_CLIENT_SECRET=...

# Optional
REFCHECKER_ADMINS=github:you   # comma-separated; first sign-in is auto-admin
MAX_CHECKS_PER_USER=3          # max concurrent checks per user (default: 3)
```

By default the callback URL is derived from `SITE_URL` as
`<SITE_URL>/api/auth/callback/{google,github,microsoft}`; override per provider
(`GOOGLE_REDIRECT_URI`, `GITHUB_REDIRECT_URI`, `MS_REDIRECT_URI`) only if you
registered a different redirect URI.

### 4. Launch & verify

```bash
docker compose up -d
# or:
pip install "academic-refchecker[llm,webui]"
REFCHECKER_MULTIUSER=true JWT_SECRET_KEY=<secret> \
  GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... refchecker-webui --port 8000

curl http://localhost:8000/api/auth/providers
# {"providers":["google","github"]}
```

---

## Teams

Once multi-user is on, signed-in users can create **Teams** and collaborate:

- **Create / list teams** — `POST /api/teams`, `GET /api/teams`.
- **Members** — `GET /api/teams/{id}/members`, `POST /api/teams/{id}/members`,
  `DELETE /api/teams/{id}/members/{user_id}`, `POST /api/teams/{id}/leave`.
- **Team-scoped shared checks** — a team's checks are visible to its members
  (`GET /api/teams/{id}/checks`), and members can **collaborate on the same batch**.
- **Activity log** — `GET /api/teams/{id}/activity` records who created the team and
  added/removed/left which member.

## Realtime presence (opt-in)

Presence is a feature of multi-user mode (it has no meaning single-user). Team
members viewing the same batch/check get a **live shared-batch presence roster** and
real-time progress over a WebSocket (`/api/ws/{session_id}`). Presence rooms are
**access-gated**: a user can only join a room they are permitted to (team
membership / ownership), and per-check progress is broadcast to everyone viewing
that batch. If you never enable multi-user mode, no presence room is ever created.

---

## Notes & honesty

- **Single-user is the default.** Nothing about accounts, Teams, or presence is
  active until you opt in.
- **Secrets are write-only.** Saved OAuth secrets are never returned to the
  browser; blank fields on save are preserved rather than cleared.
- **The CLI never authenticates** and never claims teams/collaboration.
- Place a hosted server behind a TLS-terminating reverse proxy (nginx, Caddy) for
  HTTPS; the first user to sign in is auto-admin (add more via `REFCHECKER_ADMINS`).

See also: [Feature guide](FEATURES.md) · [README — Multi-User Server](../README.md#multi-user-server-oauth).
