"""Flask + socket.io app factory."""

import os
import re
import sys
import json
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
import shutil
import atexit
from time import monotonic
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_file,
    session,
    url_for,
)
from flask_socketio import SocketIO, join_room

from server import auth
from server.events import register_events
from server.init import init_workspace
from server.persistence import read_json, write_json, read_frontmatter, ensure_within
from server.file_browser import FileBrowserError, is_textual_mime, workspace_file_path
from server.profiles import list_profiles
from server.scheduler import Scheduler
from server.teams import list_teams
from server.worker_types import ViewerContext, normalize_layout, serialize_layout
from server.workspace_manager import WorkspaceManager, projects_root
from server import service_worker as service_worker_mod
from server import mcp_auth
from server import worktrees as worktree_mod
from server.global_settings import load_global_settings
from server.terminal import TerminalManager


socketio = SocketIO()
_service_worker_atexit_registered = False

# Set of socket.io sids that authenticated via mcp_token (agent/MCP clients).
# Used by event handlers to distinguish agent-originated updates from user
# updates so the agent can't accidentally yank its own running task.
mcp_sids = set()
mcp_sid_workspace = {}

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_MAX_IMPORT_ARCHIVE_BYTES = 200 * 1024 * 1024
_MAX_IMPORT_ARCHIVE_FILES = 1000
_MAX_IMPORT_COMPRESSION_RATIO = 100
_NESTED_ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tgz",
    ".tar.gz",
    ".tbz",
    ".tbz2",
    ".tar.bz2",
    ".txz",
    ".tar.xz",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
)
_LOGIN_THROTTLE_WINDOW_SECONDS = 5 * 60
_LOGIN_THROTTLE_MAX_FAILURES = 5
_LOGIN_THROTTLE_BLOCK_SECONDS = 60
_DEFAULT_SESSION_DAYS = 30
_MAX_SESSION_DAYS = 365
def _origin_host(origin):
    if not origin:
        return ""
    parsed = urlparse(origin)
    return (parsed.hostname or "").lower()


def _request_origin(environ, *, forwarded=False):
    if not environ:
        return ""
    if forwarded:
        scheme = environ.get("HTTP_X_FORWARDED_PROTO", environ.get("wsgi.url_scheme", "http"))
        host = environ.get("HTTP_X_FORWARDED_HOST", environ.get("HTTP_HOST", ""))
    else:
        scheme = environ.get("wsgi.url_scheme", "http")
        host = environ.get("HTTP_HOST", "")
    scheme = scheme.split(",")[0].strip()
    host = host.split(",")[0].strip()
    return f"{scheme}://{host}" if scheme and host else ""


def _normalize_origin(origin):
    if not origin:
        return ""
    parsed = urlparse(origin)
    scheme = (parsed.scheme or "").lower()
    netloc = (parsed.netloc or "").lower()
    if not scheme or not netloc:
        return ""
    return f"{scheme}://{netloc}"


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _session_lifetime():
    days = _safe_int(os.environ.get("BULLPEN_SESSION_DAYS"), _DEFAULT_SESSION_DAYS)
    days = max(1, min(days, _MAX_SESSION_DAYS))
    return timedelta(days=days)


def _current_deploy_label():
    label = (os.environ.get("BULLPEN_DEPLOY_LABEL") or "").strip()
    if not label:
        return None
    # Keep this runtime-only display string compact and single-line.
    label = re.sub(r"\s+", " ", label)
    return label[:80]


def sync_deploy_label_config(bp_dir):
    path = os.path.join(bp_dir, "config.json")
    config = read_json(path)
    label = _current_deploy_label()
    if label:
        if config.get("deploy_label") == label:
            return
        config["deploy_label"] = label
    else:
        if "deploy_label" not in config:
            return
        config.pop("deploy_label", None)
    write_json(path, config)


def _configured_allowed_origins():
    raw = os.environ.get("BULLPEN_ALLOWED_ORIGINS", "")
    allowed = set()
    for item in raw.split(","):
        normalized = _normalize_origin(item.strip())
        if normalized:
            allowed.add(normalized)
    return allowed


def _socketio_origin_allowed(origin, environ=None):
    """Allow only local, same-origin, or explicitly configured origins.

    Socket.IO event handlers trust an accepted handshake for the life of the
    session, so we keep the origin policy tight here rather than relying on a
    second per-event CSRF layer.
    """
    if not origin:
        return True

    normalized_origin = _normalize_origin(origin)
    if not normalized_origin:
        return False

    origin_host = _origin_host(normalized_origin)
    if origin_host in _LOOPBACK_HOSTS:
        return True

    same_origin = _normalize_origin(_request_origin(environ))
    forwarded_origin = _normalize_origin(_request_origin(environ, forwarded=True))
    if normalized_origin in {same_origin, forwarded_origin}:
        return True

    return normalized_origin in _configured_allowed_origins()


def create_app(
    workspace,
    no_browser=False,
    global_dir=None,
    host="127.0.0.1",
    port=5000,
    websocket_debug=False,
    start_without_project=False,
    max_handoff_depth=0,
):
    """Create and configure the Flask + SocketIO app."""
    workspace = os.path.abspath(workspace)
    startup_workspace_name = (os.environ.get("BULLPEN_WORKSPACE_NAME") or "").strip() or None
    start_without_project = bool(start_without_project) or os.environ.get("BULLPEN_START_WITHOUT_PROJECT") == "1"

    # Initialize workspace manager and register startup project unless this
    # runtime intentionally starts as an empty project shell.
    manager = WorkspaceManager(global_dir=global_dir)
    startup_id = None if start_without_project else manager.register_project(workspace, name=startup_workspace_name)
    # Activate all persisted projects so the UI can switch between them immediately.
    # The registry can contain projects from prior runs that need in-memory state.
    for entry in manager.list_projects():
        if entry["id"] == startup_id:
            continue
        try:
            manager.register_project(entry["path"], name=entry.get("name"))
        except ValueError:
            # Path is currently missing/unavailable (renamed, unmounted, etc.).
            # Keep the registry entry so it returns when the path comes back;
            # do not silently delete user data.
            continue
    bp_dir = manager.get_bp_dir(startup_id) if startup_id else None

    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
        static_url_path="",
    )

    # --- Authentication bootstrap ---------------------------------------
    # Re-read the env file on every create_app so tests (which patch the
    # global dir per-test) see a fresh state and do not leak credentials
    # between unrelated test cases.
    auth.reset_auth_cache()
    auth.load_credentials(manager.global_dir)
    app.config["SECRET_KEY"] = auth.load_or_create_secret_key(manager.global_dir)
    production = os.environ.get("BULLPEN_PRODUCTION") == "1"
    session_lifetime = _session_lifetime()
    app.config.update(
        PERMANENT_SESSION_LIFETIME=session_lifetime,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production,
    )
    if production:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    if auth.auth_enabled():
        users = auth.get_users()
        user_count = len(users)
        primary = auth.get_username() or "unknown"
        print(
            f"Bullpen auth: ENABLED ({user_count} user(s), primary={primary}, "
            f"session_days={session_lifetime.days})",
            file=sys.stderr,
        )
    else:
        print(
            "Bullpen auth: DISABLED (no credentials configured). "
            "Run `bullpen --set-password` to enable login.",
            file=sys.stderr,
        )
    # --------------------------------------------------------------------

    app.config["manager"] = manager
    app.config["startup_workspace_id"] = startup_id
    # Backward-compat: existing handlers still use these directly
    app.config["workspace"] = None if start_without_project else workspace
    app.config["bp_dir"] = bp_dir
    app.config["start_without_project"] = start_without_project
    app.config["no_browser"] = no_browser
    from server import workers as worker_mod
    app.config["MAX_HANDOFF_DEPTH"] = worker_mod.configure_handoff_depth_limit(max_handoff_depth)

    login_failures = {}

    def _client_ip():
        forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return forwarded or request.remote_addr or "unknown"

    def _login_throttle_keys(username):
        normalized = (username or "").strip().lower() or "<blank>"
        client_ip = _client_ip()
        return (("ip", client_ip), ("user", client_ip, normalized))

    def _login_bucket(key, now):
        bucket = login_failures.setdefault(key, {"failures": [], "blocked_until": 0.0})
        bucket["failures"] = [
            ts for ts in bucket["failures"]
            if now - ts <= _LOGIN_THROTTLE_WINDOW_SECONDS
        ]
        return bucket

    def _login_is_throttled(username):
        now = monotonic()
        return any(
            _login_bucket(key, now)["blocked_until"] > now
            for key in _login_throttle_keys(username)
        )

    def _record_login_failure(username):
        now = monotonic()
        throttled = False
        for key in _login_throttle_keys(username):
            bucket = _login_bucket(key, now)
            bucket["failures"].append(now)
            if len(bucket["failures"]) >= _LOGIN_THROTTLE_MAX_FAILURES:
                bucket["blocked_until"] = max(
                    bucket["blocked_until"],
                    now + _LOGIN_THROTTLE_BLOCK_SECONDS,
                )
                throttled = True
        return throttled

    def _clear_login_failures(username):
        for key in _login_throttle_keys(username):
            login_failures.pop(key, None)

    socketio.init_app(
        app,
        cors_allowed_origins=_socketio_origin_allowed,
        async_mode="threading",
        logger=websocket_debug,
        engineio_logger=websocket_debug,
    )
    app.config["terminal_manager"] = TerminalManager(socketio)

    def _portable_config(config):
        safe = dict(config or {})
        for key in ("server_host", "server_port", "mcp_token", "deploy_label"):
            safe.pop(key, None)
        return safe

    def _write_runtime_config(ws, preferred_token=None):
        token = mcp_auth.ensure_workspace_runtime_config(
            ws.bp_dir,
            host=app.config.get("host", "127.0.0.1"),
            port=app.config.get("port", 5000),
            disallowed_tokens=mcp_auth.workspace_token_set(manager.all_workspaces(), exclude_bp_dir=ws.bp_dir),
            preferred_token=preferred_token,
        )
        app.config.setdefault("mcp_tokens_by_workspace", {})
        app.config["mcp_tokens_by_workspace"][ws.id] = token

    app.config["host"] = host
    app.config["port"] = port
    global _service_worker_atexit_registered
    if not _service_worker_atexit_registered:
        atexit.register(service_worker_mod.stop_all_services)
        _service_worker_atexit_registered = True
    app.config["mcp_tokens_by_workspace"] = mcp_auth.initialize_workspace_runtime_configs(
        manager.all_workspaces(),
        host,
        port,
    )
    for ws in manager.all_workspaces():
        sync_deploy_label_config(ws.bp_dir)

    # Startup reconciliation for all registered workspaces
    for ws in manager.all_workspaces():
        reconcile(ws.bp_dir)

    # --- Public (unauthenticated) assets allowlist ---------------------
    # These paths must load without a session so the login page can be
    # rendered and styled before the user authenticates.
    PUBLIC_STATIC_FILES = {"login.html", "style.css", "favicon.ico"}

    @app.before_request
    def _gate_static_assets():
        """Gate static asset requests (served by Flask's built-in static
        handler since ``static_url_path=""``) on auth, except for the
        explicit allowlist above. Non-static routes are gated by the
        per-view ``@require_auth`` decorator instead."""
        if not auth.auth_enabled():
            return None
        if session.get("authenticated"):
            return None
        ep = request.endpoint or ""
        if ep != "static":
            return None
        filename = (request.view_args or {}).get("filename", "")
        if filename in PUBLIC_STATIC_FILES:
            return None
        if auth.is_xhr_request(request):
            return jsonify({"error": "authentication required"}), 401
        return redirect(url_for("login"))

    @app.route("/")
    @auth.require_auth
    def index():
        return app.send_static_file("index.html")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"ok": True}), 200

    # --- Login / logout -------------------------------------------------

    @app.route("/login", methods=["GET"])
    def login():
        # If auth is disabled, or the caller already has a session, send
        # them straight to the app.
        if not auth.auth_enabled() or session.get("authenticated"):
            return redirect(url_for("index"))
        # Seed a CSRF token into the session so the static page can fetch it.
        auth.generate_csrf_token()
        return app.send_static_file("login.html")

    @app.route("/login/csrf", methods=["GET"])
    def login_csrf():
        """Return a fresh CSRF token for the login form.

        Kept separate so ``login.html`` can stay static (no server-side
        templating) and fetch its token over XHR.
        """
        if not auth.auth_enabled():
            return jsonify({"csrf_token": "", "auth_enabled": False})
        token = auth.generate_csrf_token()
        return jsonify({"csrf_token": token, "auth_enabled": True})

    @app.route("/login", methods=["POST"])
    def login_submit():
        if not auth.auth_enabled():
            return redirect(url_for("index"))

        submitted_token = request.form.get("csrf_token", "")
        if not auth.validate_csrf_token(submitted_token):
            return redirect(url_for("login") + "?error=csrf")

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if _login_is_throttled(username):
            return redirect(url_for("login") + "?error=throttle")
        auth.load_credentials(manager.global_dir)
        expected_hash = auth.get_password_hash(username)

        # If the username does not exist expected_hash will be None.
        password_ok = auth.check_password(password, expected_hash)
        if not username or not password_ok:
            error = "throttle" if _record_login_failure(username) else "1"
            return redirect(url_for("login") + f"?error={error}")

        session.clear()  # prevent session fixation
        session.permanent = True
        session["authenticated"] = True
        session["username"] = username
        # Re-seed the CSRF token after login.
        auth.generate_csrf_token()
        _clear_login_failures(username)

        next_url = request.form.get("next") or request.args.get("next") or ""
        if _is_safe_next(next_url):
            return redirect(next_url)
        return redirect(url_for("index"))

    @app.route("/logout", methods=["GET"])
    def logout_get():
        abort(405)

    @app.route("/logout", methods=["POST"])
    def logout():
        if auth.auth_enabled():
            submitted_token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
            if not auth.validate_csrf_token(submitted_token):
                abort(403)
        session.clear()
        if auth.auth_enabled():
            return redirect(url_for("login"))
        return redirect(url_for("index"))

    def _workspace_id_from_args():
        return request.args.get("workspaceId") or startup_id

    def _workspace_id_from_payload(payload):
        return (payload or {}).get("workspaceId") or startup_id

    def _workspace_required_response():
        return jsonify({"error": "No active workspace. Add or select a project first."}), 400

    def _workspace_from_id(ws_id, *, activate=False):
        if not ws_id:
            return None, _workspace_required_response()
        ws = manager.get_or_activate(ws_id) if activate else manager.get(ws_id)
        if ws is None:
            return None, (jsonify({"error": "Unknown workspace"}), 404)
        return ws, None

    @app.route("/api/files/<path:filepath>")
    @auth.require_auth
    def raw_file_content(filepath):
        """Serve raw/downloadable workspace files only."""
        ws, error = _workspace_from_id(_workspace_id_from_args())
        if error:
            return error
        ws_path = ws.path
        try:
            full_path = workspace_file_path(ws_path, filepath)
        except FileBrowserError as e:
            return jsonify({"error": e.message}), e.status

        if not os.path.isfile(full_path):
            abort(404)

        # Determine if binary
        import mimetypes
        mime, _ = mimetypes.guess_type(full_path)

        # Serve the raw file directly (e.g. open HTML in browser)
        if request.args.get("raw"):
            send_kwargs = {"mimetype": mime or "text/plain"}
            if mime in {"text/html", "application/xhtml+xml"}:
                send_kwargs["as_attachment"] = True
                send_kwargs["download_name"] = os.path.basename(full_path)
            return send_file(full_path, **send_kwargs)

        if mime and (mime.startswith("image/") or not is_textual_mime(mime)):
            return send_file(full_path, mimetype=mime)

        return jsonify({"error": "Use Socket.IO file events for text file content"}), 400

    def _export_workspace_zip_bytes(ws):
        mem = BytesIO()
        with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if os.path.isdir(ws.bp_dir):
                for root, _dirs, files in os.walk(ws.bp_dir):
                    for filename in files:
                        full_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(full_path, ws.path).replace(os.sep, "/")
                        if rel_path == ".bullpen/config.json":
                            config = _portable_config(read_json(full_path))
                            zf.writestr(rel_path, json.dumps(config, indent=2))
                            continue
                        zf.write(full_path, rel_path)
        mem.seek(0)
        return mem

    def _workspace_export_meta(ws):
        # Do not expose host filesystem paths in export manifests.
        return {"id": ws.id, "name": ws.name}

    def _export_all_zip_bytes():
        mem = BytesIO()
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for ws in manager.all_workspaces():
                if not os.path.isdir(ws.bp_dir):
                    continue
                for root, _dirs, files in os.walk(ws.bp_dir):
                    for filename in files:
                        full_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(full_path, ws.bp_dir).replace(os.sep, "/")
                        arcname = f"workspaces/{ws.id}/.bullpen/{rel_path}"
                        if rel_path == "config.json":
                            config = _portable_config(read_json(full_path))
                            zf.writestr(arcname, json.dumps(config, indent=2))
                            continue
                        zf.write(full_path, arcname)
            manifest = {
                "schema": "bullpen-export-all-v1",
                "created_at": created_at,
                "workspaces": [_workspace_export_meta(ws) for ws in manager.all_workspaces()],
            }
            zf.writestr("bullpen-export.json", json.dumps(manifest, indent=2))
        mem.seek(0)
        return mem

    def _safe_extract_zip(zf, target_dir):
        total_size = 0
        total_compressed_size = 0
        file_count = 0
        for info in zf.infolist():
            name = (info.filename or "").replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            file_count += 1
            if file_count > _MAX_IMPORT_ARCHIVE_FILES:
                raise ValueError("Archive contains too many files")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if any(p == ".." for p in parts):
                raise ValueError("Archive contains invalid relative paths")
            if parts and parts[0].endswith(":"):
                raise ValueError("Archive contains invalid absolute paths")
            lower_name = "/".join(parts).lower()
            if any(lower_name.endswith(suffix) for suffix in _NESTED_ARCHIVE_SUFFIXES):
                raise ValueError("Archive contains nested archive files")
            compressed_size = max(0, int(info.compress_size or 0))
            total_compressed_size += max(1, compressed_size)
            total_size += max(0, int(info.file_size or 0))
            if total_size > _MAX_IMPORT_ARCHIVE_BYTES:
                raise ValueError("Archive is too large")
            if info.file_size > max(1, compressed_size) * _MAX_IMPORT_COMPRESSION_RATIO:
                raise ValueError("Archive contains highly compressed entries")
            if total_size > total_compressed_size * _MAX_IMPORT_COMPRESSION_RATIO:
                raise ValueError("Archive compression ratio is too high")
            dest_path = os.path.join(target_dir, *parts)
            ensure_within(dest_path, target_dir)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with zf.open(info, "r") as src, open(dest_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

    def _workspace_payload_root(extracted_root):
        explicit = os.path.join(extracted_root, ".bullpen")
        if os.path.isdir(explicit):
            return explicit
        if os.path.exists(os.path.join(extracted_root, "config.json")):
            return extracted_root
        return None

    def _replace_workspace_bp_dir(ws, source_bp_dir):
        bp_dir = ws.bp_dir
        previous_token = mcp_auth.read_workspace_mcp_token(bp_dir)
        if os.path.exists(bp_dir):
            shutil.rmtree(bp_dir)
        shutil.copytree(source_bp_dir, bp_dir)
        init_workspace(ws.path)
        _write_runtime_config(ws, preferred_token=previous_token)
        reconcile(bp_dir)
        state = load_state(bp_dir, ws.path, workspace_display=ws.name)
        state["workspaceId"] = ws.id
        state["globalSettings"] = load_global_settings(manager.global_dir)
        socketio.emit("state:init", state, to=ws.id)
        socketio.emit("files:changed", {"workspaceId": ws.id}, to=ws.id)

    @app.route("/api/export/workspace")
    @auth.require_auth
    def export_workspace():
        ws, error = _workspace_from_id(_workspace_id_from_args())
        if error:
            return error
        export_name = f"bullpen-workspace-{ws.name}-{ws.id[:8]}.zip"
        return send_file(
            _export_workspace_zip_bytes(ws),
            mimetype="application/zip",
            as_attachment=True,
            download_name=export_name,
        )

    @app.route("/api/export/all")
    @auth.require_auth
    def export_all():
        export_name = f"bullpen-all-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip"
        return send_file(
            _export_all_zip_bytes(),
            mimetype="application/zip",
            as_attachment=True,
            download_name=export_name,
        )

    @app.route("/api/import/workspace", methods=["POST"])
    @auth.require_auth
    def import_workspace():
        ws_id = _workspace_id_from_args()
        ws, error = _workspace_from_id(ws_id)
        if error:
            return error
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return jsonify({"error": "Missing upload file"}), 400
        try:
            with zipfile.ZipFile(upload.stream, "r") as zf:
                with tempfile.TemporaryDirectory(prefix="bullpen_import_") as tmp_dir:
                    _safe_extract_zip(zf, tmp_dir)
                    payload_root = _workspace_payload_root(tmp_dir)
                    if not payload_root:
                        return jsonify({"error": "Archive does not contain a workspace .bullpen payload"}), 400
                    _replace_workspace_bp_dir(ws, payload_root)
        except zipfile.BadZipFile:
            return jsonify({"error": "Invalid zip file"}), 400
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"ok": True, "imported": 1, "workspaceId": ws_id})

    @app.route("/api/import/all", methods=["POST"])
    @auth.require_auth
    def import_all():
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return jsonify({"error": "Missing upload file"}), 400
        imported = 0
        try:
            with zipfile.ZipFile(upload.stream, "r") as zf:
                with tempfile.TemporaryDirectory(prefix="bullpen_import_all_") as tmp_dir:
                    _safe_extract_zip(zf, tmp_dir)
                    workspaces_dir = os.path.join(tmp_dir, "workspaces")
                    if not os.path.isdir(workspaces_dir):
                        return jsonify({"error": "Archive does not contain a workspaces/ directory"}), 400
                    for ws in manager.all_workspaces():
                        candidate = os.path.join(workspaces_dir, ws.id)
                        if not os.path.isdir(candidate):
                            continue
                        payload_root = _workspace_payload_root(candidate)
                        if not payload_root:
                            continue
                        _replace_workspace_bp_dir(ws, payload_root)
                        imported += 1
        except zipfile.BadZipFile:
            return jsonify({"error": "Invalid zip file"}), 400
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        if imported == 0:
            return jsonify({"error": "No matching workspaces found in archive"}), 400
        return jsonify({"ok": True, "imported": imported})

    @socketio.on("connect")
    def on_connect(auth_data=None):
        # Reject unauthenticated Socket.IO upgrades. Flask-SocketIO makes
        # the HTTP session available here because the cookie is sent with
        # the WebSocket handshake; returning False refuses the connection.
        #
        # The MCP stdio server has no browser session, so it authenticates
        # by passing {"mcp_token": "<token>"} via Socket.IO ``auth``.  The
        # token is written to .bullpen/config.json on startup and is only
        # readable by processes with local filesystem access.
        token = (auth_data or {}).get("mcp_token") if isinstance(auth_data, dict) else None
        mcp_ws_id = mcp_auth.find_workspace_id_for_token(manager.all_workspaces(), token)
        is_mcp = bool(mcp_ws_id)
        if auth.auth_enabled() and not session.get("authenticated"):
            if not is_mcp:
                return False
        if is_mcp:
            mcp_sids.add(request.sid)
            mcp_sid_workspace[request.sid] = mcp_ws_id
            ws = manager.get_or_activate(mcp_ws_id)
            if not ws:
                mcp_sids.discard(request.sid)
                mcp_sid_workspace.pop(request.sid, None)
                return False
            sync_deploy_label_config(ws.bp_dir)
            join_room(ws.id)
            state = load_state(ws.bp_dir, ws.path)
            state["workspaceId"] = ws.id
            state["globalSettings"] = load_global_settings(manager.global_dir)
            socketio.emit("state:init", state, to=request.sid)
            return

        join_room("authenticated")
        socketio.emit("project:settings", {"projectsRoot": projects_root() or ""}, to=request.sid)
        ws = manager.get_or_activate(startup_id)
        if ws:
            join_room(ws.id)
            state = load_state(ws.bp_dir, ws.path, workspace_display=ws.name)
            state["workspaceId"] = ws.id
            state["globalSettings"] = load_global_settings(manager.global_dir)
            socketio.emit("state:init", state, to=request.sid)
        socketio.emit("projects:updated", manager.list_visible_projects(include_path=False), to=request.sid)

    @socketio.on("disconnect")
    def on_disconnect():
        terminal_manager = app.config.get("terminal_manager")
        if terminal_manager:
            terminal_manager.close_for_sid(request.sid)
        mcp_sids.discard(request.sid)
        mcp_sid_workspace.pop(request.sid, None)

    register_events(socketio, app)

    # Start time-based scheduler for each workspace
    for ws in manager.all_workspaces():
        scheduler = Scheduler(ws.bp_dir, socketio, ws_id=ws.id)
        scheduler.start()
        ws.scheduler = scheduler

    return app


def _is_safe_next(next_url):
    """Return True if ``next_url`` is a safe in-app redirect target.

    Accepts only paths that start with a single ``/`` and have no URL
    scheme. Rejects ``//evil.com`` (protocol-relative) and ``https://x``.
    """
    if not next_url or not isinstance(next_url, str):
        return False
    if not next_url.startswith("/"):
        return False
    if next_url.startswith("//"):
        return False
    if "://" in next_url:
        return False
    return True


def reconcile(bp_dir):
    """Startup reconciliation: make ticket frontmatter canonical.

    Worker queues are derived indexes. On startup, discard persisted queue
    references, repair interrupted in-progress tasks, and rebuild queues from
    assigned tickets so stale layout state cannot survive a restart.
    """
    layout_path = os.path.join(bp_dir, "layout.json")
    if not os.path.exists(layout_path):
        return

    config = read_json(os.path.join(bp_dir, "config.json"))
    layout = normalize_layout(read_json(layout_path), config=config)
    slots = layout.get("slots", [])
    if not isinstance(slots, list):
        slots = []
        layout["slots"] = slots

    for slot in slots:
        if slot is None:
            continue
        if slot.get("task_queue"):
            slot["task_queue"] = []
        else:
            slot.setdefault("task_queue", [])
        if slot.get("state") == "working":
            slot["state"] = "idle"

    from server.tasks import task_sort_key, update_task

    def valid_assigned_slot(value):
        if value in (None, ""):
            return None
        try:
            slot_index = int(value)
        except (TypeError, ValueError):
            return None
        if slot_index < 0 or slot_index >= len(slots):
            return None
        if not slots[slot_index]:
            return None
        return slot_index

    def with_reconcile_note(body, note):
        body = body or ""
        if note in body:
            return body
        return body.rstrip() + "\n\n" + note + "\n"

    queued = []
    tasks_dir = os.path.join(bp_dir, "tasks")
    if os.path.isdir(tasks_dir):
        for fname in sorted(os.listdir(tasks_dir)):
            if not fname.endswith(".md"):
                continue
            path = os.path.join(tasks_dir, fname)
            try:
                meta, body, slug = read_frontmatter(path)
            except Exception:
                continue
            task_id = slug or fname[:-3]
            status = meta.get("status")
            assigned_slot = valid_assigned_slot(meta.get("assigned_to"))

            if status == "in_progress":
                note = (
                    "**Interrupted run:** Bullpen restarted while this task was "
                    "in progress. Task moved to blocked."
                )
                try:
                    update_task(bp_dir, task_id, {
                        "status": "blocked",
                        "assigned_to": "",
                        "handoff_depth": 0,
                        "body": with_reconcile_note(body, note),
                    })
                except Exception:
                    pass
                continue

            if status != "assigned":
                continue

            if assigned_slot is None:
                if meta.get("assigned_to") not in (None, ""):
                    note = (
                        "**Assignment repair:** Assigned worker no longer exists. "
                        "Task moved to blocked."
                    )
                    try:
                        update_task(bp_dir, task_id, {
                            "status": "blocked",
                            "assigned_to": "",
                            "handoff_depth": 0,
                            "body": with_reconcile_note(body, note),
                        })
                    except Exception:
                        pass
                continue

            queued.append((
                assigned_slot,
                *task_sort_key({**meta, "id": task_id}),
                task_id,
            ))

    queued.sort(key=lambda item: item[:-1])
    for slot_index, *_sort_fields, task_id in queued:
        slots[slot_index].setdefault("task_queue", []).append(task_id)

    write_json(layout_path, normalize_layout(layout, config=config))

    # Check watched columns for idle on_queue workers with unclaimed tasks
    from server import workers as worker_mod
    watched_columns = set()
    for slot in layout.get("slots", []):
        if (slot
                and slot.get("activation") == "on_queue"
                and slot.get("watch_column")
                and slot.get("state") == "idle"
                and not slot.get("paused")):
            watched_columns.add(slot["watch_column"])
    for col in watched_columns:
        worker_mod.check_watch_columns(bp_dir, col)
    worker_mod.drain_runnable_queues(bp_dir)

    workspace = os.path.dirname(bp_dir)
    try:
        worktree_mod.reconcile_worktrees(workspace, bp_dir)
    except Exception:
        pass


def load_state(bp_dir, workspace, workspace_display=None):
    """Load full app state from .bullpen/ files."""
    config = read_json(os.path.join(bp_dir, "config.json"))
    if not isinstance(config.get("theme"), str):
        config["theme"] = "dark"
    if config.get("ambient_preset") in ("", False):
        config["ambient_preset"] = None
    elif config.get("ambient_preset") is not None and not isinstance(config.get("ambient_preset"), str):
        config["ambient_preset"] = None
    try:
        ambient_volume = int(config.get("ambient_volume", 40))
    except (TypeError, ValueError):
        ambient_volume = 40
    config["ambient_volume"] = max(0, min(100, ambient_volume))
    layout = read_json(os.path.join(bp_dir, "layout.json"))
    layout = serialize_layout(layout, viewer=ViewerContext(can_edit=True), config=config)

    # Load all tasks
    tasks = []
    tasks_dir = os.path.join(bp_dir, "tasks")
    if os.path.isdir(tasks_dir):
        for fname in sorted(os.listdir(tasks_dir)):
            if fname.endswith(".md"):
                path = os.path.join(tasks_dir, fname)
                meta, body, slug = read_frontmatter(path)
                task = {**meta, "id": slug or fname[:-3], "body": body}
                tasks.append(task)

    profiles = list_profiles(bp_dir)
    teams = list_teams(bp_dir)

    return {
        "workspace": workspace_display or workspace,
        "config": config,
        "layout": layout,
        "tasks": tasks,
        "profiles": profiles,
        "teams": teams,
    }
