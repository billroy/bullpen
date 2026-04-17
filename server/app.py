"""Flask + socket.io app factory."""

import os
import re
import subprocess
import sys
import json
import tempfile
import zipfile
from datetime import datetime, timezone
from io import BytesIO
import shutil
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
from server.persistence import read_json, write_json, read_frontmatter, ensure_within, atomic_write
from server.transfer import transfer_worker, TransferError
from server.profiles import list_profiles
from server.scheduler import Scheduler
from server.teams import list_teams
from server.workspace_manager import WorkspaceManager


socketio = SocketIO()

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_TRUSTED_TUNNEL_SUFFIXES = (".ngrok-free.app", ".ngrok.app", ".ngrok.io", ".sprites.app")
_MAX_IMPORT_ARCHIVE_BYTES = 200 * 1024 * 1024


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


def _socketio_origin_allowed(origin, environ=None):
    """Allow local Bullpen clients and trusted tunnel hosts without wildcard CORS."""
    if not origin:
        return True

    origin_host = _origin_host(origin)
    if origin_host in _LOOPBACK_HOSTS:
        return True

    same_origin = _request_origin(environ)
    forwarded_origin = _request_origin(environ, forwarded=True)
    if origin in {same_origin, forwarded_origin}:
        return True

    return any(origin_host.endswith(suffix) for suffix in _TRUSTED_TUNNEL_SUFFIXES)


def create_app(
    workspace,
    no_browser=False,
    global_dir=None,
    host="127.0.0.1",
    port=5000,
    websocket_debug=False,
):
    """Create and configure the Flask + SocketIO app."""
    workspace = os.path.abspath(workspace)

    # Initialize workspace manager and register startup project
    manager = WorkspaceManager(global_dir=global_dir)
    startup_id = manager.register_project(workspace)
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
    bp_dir = manager.get_bp_dir(startup_id)

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
    app.config.update(
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
            f"Bullpen auth: ENABLED ({user_count} user(s), primary={primary})",
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
    app.config["workspace"] = workspace
    app.config["bp_dir"] = bp_dir
    app.config["no_browser"] = no_browser

    socketio.init_app(
        app,
        cors_allowed_origins=_socketio_origin_allowed,
        async_mode="threading",
        logger=websocket_debug,
        engineio_logger=websocket_debug,
    )

    # Store server address and a per-run MCP token so the stdio MCP server
    # (which has no session cookie) can authenticate via Socket.IO ``auth``.
    import secrets as _secrets
    mcp_token = _secrets.token_urlsafe(32)
    app.config["host"] = host
    app.config["port"] = port
    app.config["mcp_token"] = mcp_token
    for ws in manager.all_workspaces():
        config = read_json(os.path.join(ws.bp_dir, "config.json"))
        config["server_host"] = host
        config["server_port"] = port
        config["mcp_token"] = mcp_token
        write_json(os.path.join(ws.bp_dir, "config.json"), config)

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
        auth.load_credentials(manager.global_dir)
        expected_hash = auth.get_password_hash(username)

        # If the username does not exist expected_hash will be None.
        password_ok = auth.check_password(password, expected_hash)
        if not username or not password_ok:
            return redirect(url_for("login") + "?error=1")

        session.clear()  # prevent session fixation
        session["authenticated"] = True
        session["username"] = username
        # Re-seed the CSRF token after login.
        auth.generate_csrf_token()

        next_url = request.form.get("next") or request.args.get("next") or ""
        if _is_safe_next(next_url):
            return redirect(next_url)
        return redirect(url_for("index"))

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        session.clear()
        if auth.auth_enabled():
            return redirect(url_for("login"))
        return redirect(url_for("index"))

    @app.route("/api/commits")
    @auth.require_auth
    def get_commits():
        """Return git log entries for the active workspace."""
        ws_id = request.args.get("workspaceId", startup_id)
        ws_path = manager.get_workspace_path(ws_id)
        try:
            count = min(max(int(request.args.get("count", 10)), 1), 50)
        except (ValueError, TypeError):
            count = 10
        try:
            offset = max(int(request.args.get("offset", 0)), 0)
        except (ValueError, TypeError):
            offset = 0

        # Field separator (\x1f = ASCII unit separator) and record separator (\x1e = record separator)
        fmt = "%H\x1f%h\x1f%s\x1f%an\x1f%ai\x1f%b\x1e"
        try:
            result = subprocess.run(
                ["git", "log", f"-n{count}", f"--skip={offset}", f"--format={fmt}"],
                capture_output=True, text=True, cwd=ws_path, timeout=10,
            )
        except Exception as e:
            return jsonify({"commits": [], "has_more": False, "error": str(e)}), 500

        if result.returncode != 0:
            return jsonify({"commits": [], "has_more": False, "error": "Not a git repository"})

        commits = []
        for record in result.stdout.split("\x1e"):
            record = record.strip()
            if not record:
                continue
            parts = record.split("\x1f", 5)
            if len(parts) < 5:
                continue
            commits.append({
                "hash": parts[0].strip(),
                "short_hash": parts[1].strip(),
                "subject": parts[2].strip(),
                "author": parts[3].strip(),
                "date": parts[4].strip(),
                "body": parts[5].strip() if len(parts) > 5 else "",
            })

        # Check if more commits exist beyond this page
        try:
            count_result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                capture_output=True, text=True, cwd=ws_path, timeout=5,
            )
            total = int(count_result.stdout.strip()) if count_result.returncode == 0 else 0
        except Exception:
            total = 0
        has_more = (offset + len(commits)) < total

        return jsonify({"commits": commits, "has_more": has_more, "total": total})

    @app.route("/api/commits/<commit_hash>/diff")
    @auth.require_auth
    def get_commit_diff(commit_hash):
        """Return the patch for a specific commit in the active workspace."""
        ws_id = request.args.get("workspaceId", startup_id)
        ws_path = manager.get_workspace_path(ws_id)
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit_hash or ""):
            return jsonify({"error": "Invalid commit hash"}), 400
        try:
            result = subprocess.run(
                ["git", "show", "--format=", "--patch", "--no-color", commit_hash],
                capture_output=True, text=True, cwd=ws_path, timeout=10,
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        if result.returncode != 0:
            return jsonify({"error": "Commit not found"}), 404
        return jsonify({"hash": commit_hash, "diff": result.stdout})

    @app.route("/api/files")
    @auth.require_auth
    def file_tree():
        """Return workspace file tree."""
        ws_id = request.args.get("workspaceId", startup_id)
        ws_path = manager.get_workspace_path(ws_id)
        tree = build_file_tree(ws_path)
        return jsonify(tree)

    @app.route("/api/files/<path:filepath>")
    @auth.require_auth
    def file_content(filepath):
        """Return file content."""
        ws_id = request.args.get("workspaceId", startup_id)
        ws_path = manager.get_workspace_path(ws_id)
        full_path = os.path.join(ws_path, filepath)
        try:
            ensure_within(full_path, ws_path)
        except ValueError:
            abort(403)

        if not os.path.isfile(full_path):
            abort(404)

        # Determine if binary
        import mimetypes
        mime, _ = mimetypes.guess_type(full_path)

        # Serve the raw file directly (e.g. open HTML in browser)
        if request.args.get("raw"):
            from flask import send_file
            return send_file(full_path, mimetype=mime or "text/plain")

        if mime and mime.startswith("image/"):
            from flask import send_file
            return send_file(full_path, mimetype=mime)

        try:
            with open(full_path, "r", errors="replace") as f:
                content = f.read()
            return jsonify({"path": filepath, "content": content, "mime": mime or "text/plain"})
        except Exception:
            abort(500)

    @app.route("/api/files/<path:filepath>", methods=["PUT"])
    @auth.require_auth
    def file_write(filepath):
        """Write file content."""
        ws_id = request.args.get("workspaceId", startup_id)
        ws_path = manager.get_workspace_path(ws_id)
        full_path = os.path.join(ws_path, filepath)
        try:
            ensure_within(full_path, ws_path)
        except ValueError:
            abort(403)

        content = request.get_data(as_text=True)
        if len(content) > 1_000_000:
            return jsonify({"error": "File too large (max 1MB)"}), 400

        # Reject binary content
        try:
            content.encode("utf-8")
        except UnicodeEncodeError:
            return jsonify({"error": "Binary files cannot be edited"}), 400

        try:
            atomic_write(full_path, content)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/worker/transfer", methods=["POST"])
    @auth.require_auth
    def worker_transfer():
        """Copy or move a worker between workspaces."""
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"error": "invalid JSON body"}), 400

        try:
            result = transfer_worker(
                manager,
                source_workspace_id=data.get("source_workspace_id"),
                source_slot=data.get("source_slot"),
                dest_workspace_id=data.get("dest_workspace_id"),
                dest_slot=data.get("dest_slot"),
                mode=data.get("mode", "copy"),
                copy_profile=bool(data.get("copy_profile", False)),
            )
        except TransferError as e:
            return jsonify({"error": str(e)}), e.status

        # Notify destination workspace clients
        dst_ws = manager.get(data.get("dest_workspace_id"))
        if dst_ws:
            dst_layout = read_json(os.path.join(dst_ws.bp_dir, "layout.json"))
            dst_layout["workspaceId"] = dst_ws.id
            socketio.emit("layout:updated", dst_layout, to=dst_ws.id)

        # On move, also notify source workspace clients
        if data.get("mode") == "move":
            src_ws = manager.get(data.get("source_workspace_id"))
            if src_ws:
                src_layout = read_json(os.path.join(src_ws.bp_dir, "layout.json"))
                src_layout["workspaceId"] = src_ws.id
                socketio.emit("layout:updated", src_layout, to=src_ws.id)

        return jsonify(result)

    def _export_workspace_zip_bytes(ws):
        mem = BytesIO()
        with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if os.path.isdir(ws.bp_dir):
                for root, _dirs, files in os.walk(ws.bp_dir):
                    for filename in files:
                        full_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(full_path, ws.path).replace(os.sep, "/")
                        zf.write(full_path, rel_path)
        mem.seek(0)
        return mem

    def _workspace_export_meta(ws):
        # Do not expose host filesystem paths in export manifests.
        return {"id": ws.id, "name": ws.name}

    def _export_workers_zip_bytes(ws):
        mem = BytesIO()
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        layout_path = os.path.join(ws.bp_dir, "layout.json")
        layout = read_json(layout_path) if os.path.exists(layout_path) else {"slots": []}
        slots = layout.get("slots", []) if isinstance(layout, dict) else []
        workers_layout = {"slots": slots if isinstance(slots, list) else []}

        with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(".bullpen/layout.json", json.dumps(workers_layout, indent=2))

            profile_ids = set()
            for slot in workers_layout["slots"]:
                if isinstance(slot, dict) and isinstance(slot.get("profile"), str) and slot.get("profile").strip():
                    profile_ids.add(slot["profile"].strip())
            for profile_id in sorted(profile_ids):
                profile_path = os.path.join(ws.bp_dir, "profiles", f"{profile_id}.json")
                if os.path.exists(profile_path):
                    zf.write(profile_path, f".bullpen/profiles/{profile_id}.json")

            manifest = {
                "schema": "bullpen-workers-export-v1",
                "created_at": created_at,
                "workspace": _workspace_export_meta(ws),
                "profiles": sorted(profile_ids),
            }
            zf.writestr("bullpen-workers-export.json", json.dumps(manifest, indent=2))
        mem.seek(0)
        return mem

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
        for info in zf.infolist():
            name = (info.filename or "").replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if any(p == ".." for p in parts):
                raise ValueError("Archive contains invalid relative paths")
            if parts and parts[0].endswith(":"):
                raise ValueError("Archive contains invalid absolute paths")
            total_size += max(0, int(info.file_size or 0))
            if total_size > _MAX_IMPORT_ARCHIVE_BYTES:
                raise ValueError("Archive is too large")
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

    def _workers_payload_root(extracted_root):
        explicit = os.path.join(extracted_root, ".bullpen")
        if os.path.exists(os.path.join(explicit, "layout.json")):
            return explicit
        if os.path.exists(os.path.join(extracted_root, "layout.json")):
            return extracted_root
        return None

    def _replace_workspace_bp_dir(ws, source_bp_dir):
        bp_dir = ws.bp_dir
        if os.path.exists(bp_dir):
            shutil.rmtree(bp_dir)
        shutil.copytree(source_bp_dir, bp_dir)
        init_workspace(ws.path)
        reconcile(bp_dir)
        state = load_state(bp_dir, ws.path)
        state["workspaceId"] = ws.id
        socketio.emit("state:init", state, to=ws.id)
        socketio.emit("files:changed", {"workspaceId": ws.id}, to=ws.id)

    def _replace_workspace_workers(ws, source_bp_dir):
        source_layout_path = os.path.join(source_bp_dir, "layout.json")
        if not os.path.exists(source_layout_path):
            raise ValueError("Archive does not contain layout.json")

        source_layout = read_json(source_layout_path)
        if not isinstance(source_layout, dict):
            raise ValueError("layout.json must be a JSON object")
        slots = source_layout.get("slots", [])
        if not isinstance(slots, list):
            raise ValueError("layout.json slots must be a list")

        bp_dir = ws.bp_dir
        init_workspace(ws.path)
        write_json(os.path.join(bp_dir, "layout.json"), {"slots": slots})

        source_profiles_dir = os.path.join(source_bp_dir, "profiles")
        if os.path.isdir(source_profiles_dir):
            target_profiles_dir = os.path.join(bp_dir, "profiles")
            os.makedirs(target_profiles_dir, exist_ok=True)
            for filename in os.listdir(source_profiles_dir):
                if not filename.endswith(".json"):
                    continue
                src_path = os.path.join(source_profiles_dir, filename)
                dst_path = os.path.join(target_profiles_dir, filename)
                shutil.copy2(src_path, dst_path)

        reconcile(bp_dir)
        state = load_state(bp_dir, ws.path)
        state["workspaceId"] = ws.id
        socketio.emit("state:init", state, to=ws.id)

    @app.route("/api/export/workspace")
    @auth.require_auth
    def export_workspace():
        ws_id = request.args.get("workspaceId", startup_id)
        ws = manager.get(ws_id)
        if ws is None:
            return jsonify({"error": "Unknown workspace"}), 404
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

    @app.route("/api/export/workers")
    @auth.require_auth
    def export_workers():
        ws_id = request.args.get("workspaceId", startup_id)
        ws = manager.get(ws_id)
        if ws is None:
            return jsonify({"error": "Unknown workspace"}), 404
        export_name = f"bullpen-workers-{ws.name}-{ws.id[:8]}.zip"
        return send_file(
            _export_workers_zip_bytes(ws),
            mimetype="application/zip",
            as_attachment=True,
            download_name=export_name,
        )

    @app.route("/api/import/workspace", methods=["POST"])
    @auth.require_auth
    def import_workspace():
        ws_id = request.args.get("workspaceId", startup_id)
        ws = manager.get(ws_id)
        if ws is None:
            return jsonify({"error": "Unknown workspace"}), 404
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

    @app.route("/api/import/workers", methods=["POST"])
    @auth.require_auth
    def import_workers():
        ws_id = request.args.get("workspaceId", startup_id)
        ws = manager.get(ws_id)
        if ws is None:
            return jsonify({"error": "Unknown workspace"}), 404
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return jsonify({"error": "Missing upload file"}), 400
        try:
            with zipfile.ZipFile(upload.stream, "r") as zf:
                with tempfile.TemporaryDirectory(prefix="bullpen_import_workers_") as tmp_dir:
                    _safe_extract_zip(zf, tmp_dir)
                    payload_root = _workers_payload_root(tmp_dir)
                    if not payload_root:
                        return jsonify({"error": "Archive does not contain a workers payload"}), 400
                    _replace_workspace_workers(ws, payload_root)
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
        if auth.auth_enabled() and not session.get("authenticated"):
            expected = app.config.get("mcp_token")
            token = (auth_data or {}).get("mcp_token") if isinstance(auth_data, dict) else None
            if not expected or not token or token != expected:
                return False
        join_room("authenticated")
        # Join rooms for all active workspaces
        for ws in manager.all_workspaces():
            join_room(ws.id)
        # Send state for all active workspaces (to this client only)
        sid = request.sid
        for ws in manager.all_workspaces():
            state = load_state(ws.bp_dir, ws.path)
            state["workspaceId"] = ws.id
            socketio.emit("state:init", state, to=sid)
        # Send project list (to this client only)
        socketio.emit("projects:updated", manager.list_projects(), to=sid)

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


def build_file_tree(workspace):
    """Build file tree excluding .git, node_modules, gitignored paths."""
    excluded = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv"}

    # Try to get gitignored paths
    gitignored = set()
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"],
            capture_output=True, text=True, cwd=workspace, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line:
                    gitignored.add(line.rstrip("/"))
        # Always show .bullpen regardless of .gitignore
        gitignored.discard(".bullpen")
    except Exception:
        pass

    MAX_DEPTH = 20
    MAX_NODES = 10_000
    node_count = [0]  # mutable counter for nested scope

    def walk(path, rel="", depth=0):
        entries = []
        if depth >= MAX_DEPTH or node_count[0] >= MAX_NODES:
            return entries
        try:
            items = sorted(os.listdir(path))
        except PermissionError:
            return entries

        for name in items:
            if node_count[0] >= MAX_NODES:
                break
            if name.startswith(".") and name in excluded:
                continue
            rel_path = os.path.join(rel, name) if rel else name
            if rel_path in gitignored or name in excluded:
                continue
            full = os.path.join(path, name)
            node_count[0] += 1
            if os.path.islink(full):
                # Skip symlinked directories to prevent traversal/loops
                if os.path.isdir(full):
                    continue
                entries.append({"name": name, "path": rel_path, "type": "file"})
            elif os.path.isdir(full):
                children = walk(full, rel_path, depth + 1)
                entries.append({"name": name, "path": rel_path, "type": "dir", "children": children})
            else:
                entries.append({"name": name, "path": rel_path, "type": "file"})
        return entries

    return walk(workspace)


def reconcile(bp_dir):
    """Startup reconciliation: make ticket frontmatter canonical.

    Worker queues are derived indexes. On startup, discard persisted queue
    references, repair interrupted in-progress tasks, and rebuild queues from
    assigned tickets so stale layout state cannot survive a restart.
    """
    layout_path = os.path.join(bp_dir, "layout.json")
    if not os.path.exists(layout_path):
        return

    layout = read_json(layout_path)
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

    from server.tasks import update_task

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
                str(meta.get("created_at", "")),
                task_id,
            ))

    queued.sort(key=lambda item: (item[0], item[1], item[2]))
    for slot_index, _created_at, task_id in queued:
        slots[slot_index].setdefault("task_queue", []).append(task_id)

    write_json(layout_path, layout)

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


def load_state(bp_dir, workspace):
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
        "workspace": workspace,
        "config": config,
        "layout": layout,
        "tasks": tasks,
        "profiles": profiles,
        "teams": teams,
    }
