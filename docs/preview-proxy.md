# Bullpen Preview Proxy Proposal

## Problem

Fly.io Sprites expose one public HTTP service through the Sprite URL. Bullpen
uses that service today by creating the `bullpen` Sprite service with
`--http-port 8080`, so the public URL routes to Bullpen:

```text
https://<sprite>.sprites.dev/ -> Bullpen on 127.0.0.1:8080
```

That leaves no second public browser port for web apps being developed inside
the Sprite. A dev server can still listen locally inside the Sprite, such as
`127.0.0.1:5173`, but a browser outside the Sprite cannot reach that port
directly.

Normal Fly apps can define multiple services in `fly.toml`, but Sprites are a
narrower environment. The Sprite URL/service model effectively gives Bullpen
the one public web entry point. Sprite's separate proxy/tunnel support is useful
from a local CLI, but it does not solve "open the app from Bullpen in a browser"
without extra user-side setup.

## Goal

Add a Bullpen "Preview" tab that lets users view web apps running inside the
Sprite through Bullpen's existing public HTTPS origin.

The user experience should be:

1. Start a dev server inside the Sprite, for example `npm run dev`.
2. Open Bullpen.
3. Select the dev server port in a Preview tab.
4. View and interact with the app in an iframe without opening extra public
   Sprite ports.

## Proposed Shape

Bullpen should become an authenticated reverse proxy for loopback dev servers.

```text
Browser
  |
  | https://<sprite>.sprites.dev/__preview/<workspaceId>/<port>/...
  v
Bullpen on Sprite public HTTP service
  |
  | http://127.0.0.1:<port>/...
  v
Workspace dev server
```

### Backend Routes

Add authenticated preview routes to `server/app.py`, or preferably route
registration backed by a new `server/preview_proxy.py` module.

Suggested HTTP route:

```text
/__preview/<workspace_id>/<int:port>/
/__preview/<workspace_id>/<int:port>/<path:path>
```

The route should:

- require Bullpen authentication;
- validate `workspace_id`;
- validate that `port` is a loopback-only preview target;
- proxy the original method, path, query string, request body, and content type;
- forward safe response headers;
- strip hop-by-hop headers;
- rewrite redirect `Location` headers back into the preview prefix;
- avoid forwarding Bullpen session cookies to the dev server by default.

Only loopback upstreams should be allowed initially:

```text
http://127.0.0.1:<port>
http://localhost:<port>
http://[::1]:<port>
```

Do not support arbitrary upstream hosts by default. Arbitrary proxy targets
would turn this feature into an SSRF-shaped surface.

### Port Discovery

Add a small API for the Preview tab:

```text
GET /api/previews?workspaceId=<workspace_id>
```

It should return candidate listening ports, excluding Bullpen's own configured
port.

On Linux/Sprites:

- prefer `/proc/net/tcp` and `/proc/net/tcp6`, or `ss -ltnp` if available;
- list only loopback listeners by default;
- optionally annotate process names when available.

On macOS development:

- fall back to `lsof -iTCP -sTCP:LISTEN -n -P` when available.

The first implementation can also allow manual port entry. Manual entry is
important because process discovery may be incomplete inside restricted
environments.

### Frontend Tab

Add a new `PreviewTab` component and load it from `static/index.html`.

The tab should include:

- a detected-port selector;
- a manual port field;
- a refresh button;
- an iframe pointed at the selected preview URL;
- a copy/open control for the preview URL;
- clear error text when the target port is unreachable.

The main app tab list in `static/app.js` can add a static tab:

```text
Preview
```

This is a better initial product shape than hiding preview under Files, because
running app previews are operationally different from static HTML file previews.

## WebSocket Proxying

WebSocket support is necessary for modern dev servers, especially hot module
reload.

A browser WebSocket starts as an HTTP Upgrade request. Once the upstream dev
server accepts the handshake, the connection becomes long-lived and
bidirectional:

```text
Browser iframe
  |
  | wss://<sprite>.sprites.dev/__preview/ws/<workspaceId>/<port>/<path>
  v
Bullpen
  |
  | ws://127.0.0.1:<port>/<path>
  v
Dev server
```

The browser cannot connect directly to `ws://127.0.0.1:5173`, because that
would mean the user's local machine, not the Sprite. It also cannot connect to
`wss://<sprite>.sprites.dev:5173`, because port `5173` is not publicly routed.
The WebSocket URL must point back through Bullpen's public origin.

Suggested WebSocket route:

```text
/__preview/ws/<workspace_id>/<int:port>/
/__preview/ws/<workspace_id>/<int:port>/<path:path>
```

The proxy should:

- require Bullpen authentication before accepting the upgrade;
- validate the same target rules as HTTP preview routes;
- accept the browser WebSocket;
- open an upstream WebSocket to `ws://127.0.0.1:<port>/<path>`;
- copy frames browser-to-upstream and upstream-to-browser until either side
  closes;
- forward `Sec-WebSocket-Protocol` when present;
- avoid forwarding Bullpen cookies upstream;
- preserve query strings;
- handle ping/pong and close frames cleanly.

Bullpen already depends on `simple-websocket` and `websocket-client`, which are
enough for a first bridge:

- `simple-websocket` can accept the browser-side WebSocket from the Flask/Werkzeug
  request environment.
- `websocket-client` can connect to the upstream dev server.
- Two worker threads can pump frames in both directions.

Pseudo-code:

```python
@app.route("/__preview/ws/<workspace_id>/<int:port>/<path:path>")
@auth.require_auth
def preview_ws(workspace_id, port, path):
    validate_preview_target(workspace_id, port)

    downstream = Server.accept(request.environ)
    upstream = websocket.create_connection(
        build_upstream_ws_url(port, path, request.query_string),
        subprotocols=parse_subprotocols(request.headers),
        header=filtered_ws_headers(request.headers),
    )

    start_thread(copy_frames, downstream, upstream)
    copy_frames(upstream, downstream)
```

This should be tested under the same server mode Bullpen uses in production
Sprites. Raw WebSocket proxying can be awkward under plain WSGI servers, even
when Flask-SocketIO works for Bullpen's own Socket.IO traffic. If the direct
Flask route proves brittle, run the preview WebSocket bridge through a small
socket-capable helper server inside the same Bullpen process, or switch the
preview proxy implementation to a WSGI/ASGI-compatible layer that handles
upgrades reliably.

## Path Prefix Challenge

The main product risk is not basic byte forwarding. It is that many dev apps
assume they are mounted at `/`.

This preview URL:

```text
https://<sprite>.sprites.dev/__preview/<workspaceId>/5173/
```

works naturally for relative asset paths:

```html
<script src="./assets/app.js"></script>
```

But absolute paths escape the preview prefix:

```html
<script src="/assets/app.js"></script>
fetch("/api/data")
new WebSocket("ws://localhost:5173/")
```

Those requests would hit Bullpen routes instead of the dev server unless Bullpen
rewrites them or the dev server is configured with a preview base path.

## Implementation Plan

### Phase 1: Useful MVP

Build a path-prefix HTTP proxy and Preview tab.

Included:

- authenticated HTTP proxy route;
- manual port entry;
- simple port discovery;
- iframe preview;
- redirect rewriting;
- basic error handling.

Known limitations:

- apps with root-absolute assets may be partially broken;
- dev-server HMR may not work;
- WebSocket traffic may be unsupported or experimental.

This phase is still valuable for static sites, simple local servers, Flask apps,
FastAPI apps, and dev servers configured with a base path.

### Phase 2: WebSocket and HMR

Add the WebSocket route and frame bridge.

Focus first on common dev-server flows:

- Vite HMR;
- React dev server websockets;
- Next.js dev websocket paths if relevant.

Where possible, prefer documented dev-server configuration over aggressive
rewriting. For example, Vite can often be configured to use a specific HMR
host, protocol, client port, and path. In a Sprite preview, the desired browser
target is:

```text
wss://<sprite>.sprites.dev/__preview/ws/<workspaceId>/<port>/...
```

while the upstream target remains:

```text
ws://127.0.0.1:<port>/...
```

### Phase 3: Compatibility Rewrites

Add targeted HTML and response rewriting:

- rewrite `src="/..."`, `href="/..."`, and `action="/..."`;
- rewrite selected JavaScript dev-client websocket URLs where safe;
- rewrite redirect locations;
- possibly inject a small base/helper script into HTML responses.

This should be conservative. Rewriting arbitrary JavaScript is fragile and can
create surprising behavior.

### Phase 4: Opt-In Root Preview Mode

Consider an opt-in mode where Bullpen reserves a preview session and proxies
selected root paths to the active preview.

This could make absolute-path apps work much better:

```text
/@vite/client -> active preview server
/assets/...   -> active preview server
/api/...      -> active preview server, if not claimed by Bullpen
```

The downside is route ambiguity. Bullpen already owns `/api`, `/socket.io`,
static assets, and app routes. Root preview mode should be explicit, temporary,
and easy to disable.

## Security Model

Preview proxying should be treated as local development access exposed through
Bullpen authentication.

Rules:

- require Bullpen auth for all preview HTTP and WebSocket routes;
- allow only loopback upstream hosts by default;
- reject Bullpen's own port as an upstream target;
- reject privileged or invalid ports unless explicitly allowed;
- do not forward Bullpen cookies or CSRF tokens upstream;
- strip hop-by-hop headers such as `Connection`, `Upgrade`,
  `Proxy-Authenticate`, `Proxy-Authorization`, `TE`, `Trailer`,
  `Transfer-Encoding`, and `Keep-Alive`;
- cap request/response header sizes where practical;
- add clear logging for preview target, status, and failures without logging
  sensitive request bodies.

The browser will see the preview as same-origin with Bullpen. That is useful
for the one-port Sprite constraint, but it means untrusted dev apps inside the
iframe should be isolated. Use iframe sandboxing where possible, then selectively
relax capabilities required for realistic app previews.

## Open Questions

- Should preview availability be global per workspace, or should each browser
  tab maintain its own selected port?
- Should Bullpen persist recently used preview ports in `.bullpen/config.json`?
- How much iframe sandboxing is compatible with common dev apps?
- Should the proxy support HTTPS upstreams on loopback, or only HTTP initially?
- Should root preview mode ever proxy `/api`, or should Bullpen's API namespace
  always win?
- Is the current Flask/Werkzeug production path sufficient for accepted raw
  WebSocket upgrade routes, or do we need a dedicated bridge server?

## Recommendation

Build the Preview tab and HTTP proxy first, with honest limitations. Then add
WebSocket support around a small set of real dev-server test cases, starting
with Vite. This gives Sprite users immediate value while keeping the riskier
HMR and path-rewrite work grounded in observed failures instead of speculative
rewrites.
