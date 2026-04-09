# Login

Bullpen supports optional single-user username/password authentication.
Credentials protect both the HTTP API and Socket.IO connections; all
unauthenticated requests to protected routes are rejected at the server.

Authentication is **opt-in**. When no credential file exists, Bullpen
behaves exactly as before — no login screen, no session cookie, no
Socket.IO gate. This keeps the localhost developer experience zero-config.

## Enabling auth

Run the interactive password setter from the Bullpen project root:

```
python bullpen.py --set-password
```

You will be prompted for a username and password (typed twice, never
echoed). The hashed password is written to the global Bullpen env file:

```
~/.bullpen/.env      (macOS / Linux)
```

The file is created with mode `600` (user-only read/write) so the hash
is never world-readable. Restart Bullpen to apply:

```
python bullpen.py
```

On startup Bullpen prints the auth status to stderr:

```
Bullpen auth: ENABLED (user=admin)
```

or

```
Bullpen auth: DISABLED (no credentials configured). Run `bullpen --set-password` to enable login.
```

## Env file format

The file is parsed manually as a simple INI-like `KEY=VALUE` document
(no dotenv, YAML, or TOML dependencies). Lines beginning with `#` and
blank lines are ignored. Values may optionally be single- or
double-quoted; no escaping or interpolation is performed.

```
BULLPEN_USERNAME=admin
BULLPEN_PASSWORD_HASH=scrypt:32768:8:1$abcd...$...
BULLPEN_SECRET_KEY=<random 64-char hex>
```

`BULLPEN_PASSWORD_HASH` is a Werkzeug password hash — the same format
produced by `werkzeug.security.generate_password_hash`. Werkzeug is
already a transitive dependency of Flask, so no new packages are
required.

`BULLPEN_SECRET_KEY` is generated automatically on first startup if
absent and written back to the env file. It signs Flask session
cookies, so persisting it means sessions survive restarts.

## Changing the password

Re-run `bullpen --set-password` and enter the new credentials. The
command preserves `BULLPEN_SECRET_KEY`, so active sessions remain valid
across a rotation. To force all clients to sign in again, delete the
env file and run `--set-password` again.

## Disabling auth

Delete `~/.bullpen/.env` (or any file named `.env` in the global dir).
On the next restart Bullpen will report auth disabled, and the
`require_auth` decorator becomes a pass-through. Existing sessions are
invalidated because their Flask secret key was in that file.

## How it works

- **HTTP**: every protected view is wrapped with a `require_auth`
  decorator. When auth is enabled, unauthenticated browser requests are
  redirected (302) to `/login?next=<original-path>`, while XHR requests
  (those carrying `X-Requested-With: XMLHttpRequest` or an
  `Accept: application/json` header without `text/html`) receive a
  `401 application/json` response so the Vue frontend can handle the
  redirect itself rather than parsing the login page HTML.
- **Static assets**: `/login.html`, `/style.css`, and `/favicon.ico` are
  served publicly so the login page can render before the user signs
  in. Every other static asset (including `index.html` and `app.js`) is
  gated.
- **Socket.IO**: the `connect` handler checks the Flask session and
  returns `False` — the standard Flask-SocketIO mechanism for rejecting
  an upgrade — if the caller is not authenticated. The browser session
  cookie is sent with the WebSocket upgrade request, so no separate
  Socket.IO auth token is needed.
- **CSRF**: the login form ships with a per-session CSRF token fetched
  from `/login/csrf` and verified on POST. Failed validation redirects
  back to `/login?error=csrf`. `SameSite=Lax` cookies provide partial
  CSRF protection at the transport layer as well.
- **Multi-workspace scope**: one Flask app serves every registered
  workspace, so a single login authenticates the user for all of them.
  Per-workspace auth is a future concern.

## Deploying remotely (TLS note)

Bullpen sets `SESSION_COOKIE_HTTPONLY=True` and
`SESSION_COOKIE_SAMESITE=Lax`, but does **not** set `SESSION_COOKIE_SECURE`
by default so that non-HTTPS localhost access still works. When you
expose Bullpen outside of localhost — for example over a tunnel or via
a reverse proxy — put TLS in front (nginx + Let's Encrypt, Caddy,
Cloudflare Tunnel, etc.) so the session cookie is never transmitted in
plaintext.

Login credentials still protect the service over plain HTTP, but
anyone who can observe the network can capture the session cookie and
replay it. Treat HTTPS as a requirement for any non-local deployment.

## Out of scope

The following are intentionally not supported by the minimal auth
feature:

- Multiple users or per-user permissions
- OAuth, OIDC, API tokens
- Password reset flow
- Rate limiting on the login endpoint (future hardening)
- HTTPS termination inside Bullpen itself (handled by reverse proxy)
