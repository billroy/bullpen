"""Flask + socket.io app factory."""

import os
import subprocess
import sys

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)
from flask_socketio import SocketIO, join_room

from server import auth
from server.events import register_events
from server.init import init_workspace
from server.persistence import read_json, write_json, read_frontmatter, ensure_within, atomic_write
from server.profiles import list_profiles
from server.scheduler import Scheduler
from server.teams import list_teams
from server.workspace_manager import WorkspaceManager


socketio = SocketIO()


def create_app(workspace, no_browser=False, global_dir=None, host="127.0.0.1", port=5000):
    """Create and configure the Flask + SocketIO app."""
    workspace = os.path.abspath(workspace)

    # Initialize workspace manager and register startup project
    manager = WorkspaceManager(global_dir=global_dir)
    startup_id = manager.register_project(workspace)
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
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Left False so non-HTTPS localhost access still works; production
        # deployments should terminate TLS at a reverse proxy. See docs/login.md.
        SESSION_COOKIE_SECURE=False,
    )
    if auth.auth_enabled():
        print(
            f"Bullpen auth: ENABLED (user={auth.get_username()})",
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

    if host == "0.0.0.0":
        cors_origin = "*"
    else:
        cors_origin = f"http://{host}:{port}"
    socketio.init_app(app, cors_allowed_origins=cors_origin, async_mode="threading")

    # Store server address so MCP tools can connect back
    app.config["host"] = host
    app.config["port"] = port
    for ws in manager.all_workspaces():
        config = read_json(os.path.join(ws.bp_dir, "config.json"))
        config["server_host"] = host
        config["server_port"] = port
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
        expected_user = auth.get_username()
        _, expected_hash = auth.load_credentials(manager.global_dir)

        # Always call check_password so timing is roughly constant regardless
        # of whether the username matched.
        password_ok = auth.check_password(password, expected_hash)
        if not username or username != expected_user or not password_ok:
            return redirect(url_for("login") + "?error=1")

        session.clear()  # prevent session fixation
        session["authenticated"] = True
        session["username"] = expected_user
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

    @socketio.on("connect")
    def on_connect():
        # Reject unauthenticated Socket.IO upgrades. Flask-SocketIO makes
        # the HTTP session available here because the cookie is sent with
        # the WebSocket handshake; returning False refuses the connection.
        if auth.auth_enabled() and not session.get("authenticated"):
            return False
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
    """Startup reconciliation: reset workers, fix interrupted tasks."""
    layout_path = os.path.join(bp_dir, "layout.json")
    if not os.path.exists(layout_path):
        return

    layout = read_json(layout_path)
    changed = False

    for slot in layout.get("slots", []):
        if slot is None:
            continue
        # Reset working workers to idle
        if slot.get("state") == "working":
            slot["state"] = "idle"
            changed = True
            # Move in-progress tasks to blocked
            for task_id in slot.get("task_queue", []):
                task_path = os.path.join(bp_dir, "tasks", f"{task_id}.md")
                if os.path.exists(task_path):
                    from server.tasks import update_task
                    try:
                        update_task(bp_dir, task_id, {"status": "blocked"})
                    except Exception:
                        pass

    if changed:
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
