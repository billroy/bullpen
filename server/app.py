"""Flask + socket.io app factory."""

import os
import subprocess

from flask import Flask, jsonify, request, abort
from flask_socketio import SocketIO

from server.events import register_events
from server.init import init_workspace
from server.persistence import read_json, write_json, read_frontmatter, ensure_within, atomic_write
from server.profiles import list_profiles
from server.scheduler import Scheduler
from server.teams import list_teams
from server.workspace_manager import WorkspaceManager


socketio = SocketIO()


def create_app(workspace, no_browser=False, global_dir=None):
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
    app.config["manager"] = manager
    app.config["startup_workspace_id"] = startup_id
    # Backward-compat: existing handlers still use these directly
    app.config["workspace"] = workspace
    app.config["bp_dir"] = bp_dir
    app.config["no_browser"] = no_browser

    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")

    # Startup reconciliation for all registered workspaces
    for ws in manager.all_workspaces():
        reconcile(ws.bp_dir)

    @app.route("/")
    def index():
        return app.send_static_file("index.html")

    @app.route("/api/browse")
    def browse_dirs():
        """List directories at a given path for the directory picker."""
        path = request.args.get("path", os.path.expanduser("~"))
        path = os.path.expanduser(path)
        path = os.path.abspath(path)

        if not os.path.isdir(path):
            return jsonify({"error": "Not a directory"}), 400

        dirs = []
        try:
            for name in sorted(os.listdir(path)):
                if name.startswith("."):
                    continue
                full = os.path.join(path, name)
                if os.path.isdir(full):
                    dirs.append(name)
        except PermissionError:
            return jsonify({"error": "Permission denied"}), 403

        return jsonify({"path": path, "dirs": dirs})

    @app.route("/api/files")
    def file_tree():
        """Return workspace file tree."""
        ws_id = request.args.get("workspaceId", startup_id)
        ws_path = manager.get_workspace_path(ws_id)
        tree = build_file_tree(ws_path)
        return jsonify(tree)

    @app.route("/api/files/<path:filepath>")
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
        # Send state for all active workspaces
        for ws in manager.all_workspaces():
            state = load_state(ws.bp_dir, ws.path)
            state["workspaceId"] = ws.id
            socketio.emit("state:init", state)
        # Send project list
        socketio.emit("projects:updated", manager.list_projects())

    register_events(socketio, app)

    # Start time-based scheduler for each workspace
    for ws in manager.all_workspaces():
        scheduler = Scheduler(ws.bp_dir, socketio, ws_id=ws.id)
        scheduler.start()
        ws.scheduler = scheduler

    return app


def build_file_tree(workspace):
    """Build file tree excluding .bullpen, .git, node_modules, gitignored paths."""
    excluded = {".bullpen", ".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv"}

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
    except Exception:
        pass

    def walk(path, rel=""):
        entries = []
        try:
            items = sorted(os.listdir(path))
        except PermissionError:
            return entries

        for name in items:
            if name.startswith(".") and name in excluded:
                continue
            rel_path = os.path.join(rel, name) if rel else name
            if rel_path in gitignored or name in excluded:
                continue
            full = os.path.join(path, name)
            if os.path.isdir(full):
                children = walk(full, rel_path)
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
