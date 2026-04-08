"""Multi-workspace manager for concurrent project support."""

import json
import os
import threading

from server.init import init_workspace
from server.persistence import read_json, write_json


GLOBAL_DIR = os.path.expanduser("~/.bullpen")
REGISTRY_PATH = os.path.join(GLOBAL_DIR, "projects.json")


class WorkspaceState:
    """Runtime state for a single workspace."""

    def __init__(self, workspace_id, path, name):
        self.id = workspace_id
        self.path = path
        self.name = name
        self.bp_dir = os.path.join(path, ".bullpen")
        self.lock = threading.Lock()
        self.scheduler = None

    def to_dict(self):
        return {"id": self.id, "path": self.path, "name": self.name}


class WorkspaceManager:
    """Manages multiple concurrent workspace states."""

    def __init__(self, global_dir=None):
        self._workspaces = {}  # id -> WorkspaceState
        self._lock = threading.Lock()
        self._global_dir = global_dir or GLOBAL_DIR
        self._registry_path = os.path.join(self._global_dir, "projects.json")
        self._ensure_global_dir()
        self._registry = self._load_registry()
        self._prune_stale()

    # --- Registry I/O ---

    def _ensure_global_dir(self):
        os.makedirs(self._global_dir, exist_ok=True)

    def _load_registry(self):
        if os.path.exists(self._registry_path):
            try:
                with open(self._registry_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save_registry(self):
        self._ensure_global_dir()
        with open(self._registry_path, "w") as f:
            json.dump(self._registry, f, indent=2)

    def _prune_stale(self):
        """Remove registry entries whose paths no longer exist on disk."""
        before = len(self._registry)
        self._registry = [e for e in self._registry if os.path.isdir(e.get("path", ""))]
        if len(self._registry) < before:
            self._save_registry()

    # --- Project management ---

    def _find_by_path(self, path):
        """Find a registry entry by absolute path."""
        for entry in self._registry:
            if entry["path"] == path:
                return entry
        return None

    def _generate_id(self):
        import uuid
        return str(uuid.uuid4())

    def register_project(self, path, name=None):
        """Register a project path. Returns the workspace ID.

        If the path was previously registered, reuses its ID.
        Initializes the workspace and creates a WorkspaceState.
        """
        path = os.path.abspath(path)
        real_path = os.path.realpath(path)
        if not os.path.isdir(real_path):
            raise ValueError(f"Not a directory: {path}")

        # Reject non-absolute paths or paths with ..
        if ".." in path.split(os.sep):
            raise ValueError(f"Invalid path: {path}")

        # Use resolved path to prevent symlink-based traversal
        path = real_path

        with self._lock:
            # Check if already registered
            entry = self._find_by_path(path)
            if entry:
                ws_id = entry["id"]
                # Update name if provided
                if name and name != entry["name"]:
                    entry["name"] = name
                    self._save_registry()
            else:
                ws_id = self._generate_id()
                if name is None:
                    name = os.path.basename(path)
                entry = {"id": ws_id, "path": path, "name": name}
                self._registry.append(entry)
                self._save_registry()

            # Initialize workspace if not already active
            if ws_id not in self._workspaces:
                bp_dir = init_workspace(path)
                ws = WorkspaceState(ws_id, path, entry["name"])
                self._workspaces[ws_id] = ws

            return ws_id

    def remove_project(self, workspace_id):
        """Remove a project from the registry and tear down its state.

        Does not delete .bullpen/ data on disk.
        """
        with self._lock:
            ws = self._workspaces.pop(workspace_id, None)
            if ws and ws.scheduler:
                ws.scheduler.stop()

            self._registry = [e for e in self._registry if e["id"] != workspace_id]
            self._save_registry()

    def get(self, workspace_id):
        """Get a WorkspaceState by ID. Returns None if not found."""
        return self._workspaces.get(workspace_id)

    def get_bp_dir(self, workspace_id):
        """Get the .bullpen directory path for a workspace."""
        ws = self._workspaces.get(workspace_id)
        if ws is None:
            raise KeyError(f"Unknown workspace: {workspace_id}")
        return ws.bp_dir

    def get_workspace_path(self, workspace_id):
        """Get the workspace directory path."""
        ws = self._workspaces.get(workspace_id)
        if ws is None:
            raise KeyError(f"Unknown workspace: {workspace_id}")
        return ws.path

    def all_workspaces(self):
        """Return list of all active WorkspaceState objects."""
        return list(self._workspaces.values())

    def all_ids(self):
        """Return list of all active workspace IDs."""
        return list(self._workspaces.keys())

    def list_projects(self):
        """Return registry entries for all registered projects."""
        return [e.copy() for e in self._registry]

    @property
    def default_id(self):
        """Return the ID of the first registered workspace, or None."""
        if self._workspaces:
            return next(iter(self._workspaces))
        return None
