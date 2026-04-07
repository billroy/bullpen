"""Flask + socket.io app factory."""

import os

from flask import Flask
from flask_socketio import SocketIO

from server.events import register_events
from server.init import init_workspace
from server.persistence import read_json


socketio = SocketIO()


def create_app(workspace, no_browser=False):
    """Create and configure the Flask + SocketIO app."""
    workspace = os.path.abspath(workspace)
    bp_dir = init_workspace(workspace)

    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
        static_url_path="",
    )
    app.config["workspace"] = workspace
    app.config["bp_dir"] = bp_dir
    app.config["no_browser"] = no_browser

    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")

    @app.route("/")
    def index():
        return app.send_static_file("index.html")

    @socketio.on("connect")
    def on_connect():
        state = load_state(app.config["bp_dir"], workspace)
        socketio.emit("state:init", state)

    register_events(socketio, app)

    return app


def load_state(bp_dir, workspace):
    """Load full app state from .bullpen/ files."""
    config = read_json(os.path.join(bp_dir, "config.json"))
    layout = read_json(os.path.join(bp_dir, "layout.json"))

    # Load all tasks
    tasks = []
    tasks_dir = os.path.join(bp_dir, "tasks")
    if os.path.isdir(tasks_dir):
        from server.persistence import read_frontmatter
        for fname in sorted(os.listdir(tasks_dir)):
            if fname.endswith(".md"):
                path = os.path.join(tasks_dir, fname)
                meta, body, slug = read_frontmatter(path)
                task = {**meta, "id": slug or fname[:-3], "body": body}
                tasks.append(task)

    return {
        "workspace": workspace,
        "config": config,
        "layout": layout,
        "tasks": tasks,
    }
