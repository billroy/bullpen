"""Tests for workspace manager project registry lifecycle."""

import json
import os
import shutil

from server.persistence import read_json, write_json
from server.workspace_manager import WorkspaceManager


def test_remove_then_readd_path_preserves_workspace_data(tmp_path):
    global_dir = tmp_path / "global"
    workspace = tmp_path / "project-a"
    workspace.mkdir(parents=True, exist_ok=True)

    manager = WorkspaceManager(global_dir=str(global_dir))
    ws_id = manager.register_project(str(workspace), name="Project A")
    bp_dir = manager.get_bp_dir(ws_id)

    # Seed project-specific data and one ticket file.
    config_path = os.path.join(bp_dir, "config.json")
    config = read_json(config_path)
    config["theme"] = "nord"
    write_json(config_path, config)

    tasks_dir = os.path.join(bp_dir, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)
    task_path = os.path.join(tasks_dir, "persist-me.md")
    with open(task_path, "w", encoding="utf-8") as f:
        f.write("---\ntitle: Persist me\nstatus: inbox\n---\n\nBody.\n")

    manager.remove_project(ws_id)
    assert os.path.exists(task_path)

    ws_id_2 = manager.register_project(str(workspace), name="Project A")
    bp_dir_2 = manager.get_bp_dir(ws_id_2)

    # Re-registering the same path points back to the same .bullpen data.
    assert bp_dir_2 == bp_dir
    assert os.path.exists(task_path)
    assert read_json(config_path)["theme"] == "nord"


def test_registry_preserves_entries_with_missing_paths(tmp_path):
    """A project whose directory is temporarily missing must NOT be deleted
    from the registry on manager startup. Re-instantiating the manager has
    historically pruned such entries silently, destroying user data when a
    path was unmounted/renamed/on an external volume at startup."""
    global_dir = tmp_path / "global"
    available = tmp_path / "available"
    missing = tmp_path / "missing"
    available.mkdir()
    missing.mkdir()

    manager = WorkspaceManager(global_dir=str(global_dir))
    available_id = manager.register_project(str(available), name="available")
    missing_id = manager.register_project(str(missing), name="missing")

    # Simulate the directory disappearing between sessions
    # (rename, unmount, network drive offline, etc.).
    shutil.rmtree(missing)
    assert not os.path.isdir(missing)

    # New manager instance, as on server restart.
    manager2 = WorkspaceManager(global_dir=str(global_dir))
    ids = {e["id"] for e in manager2.list_projects()}
    assert available_id in ids
    assert missing_id in ids, "missing-path entry was silently pruned"

    # And the on-disk registry must still contain both entries.
    with open(global_dir / "projects.json") as f:
        on_disk = json.load(f)
    assert {e["id"] for e in on_disk} == {available_id, missing_id}


def test_manager_init_does_not_rewrite_registry(tmp_path):
    """Instantiating WorkspaceManager must not modify projects.json. A
    write-on-init is what made the data loss permanent — by the time the
    user noticed, the prior registry was gone."""
    global_dir = tmp_path / "global"
    workspace = tmp_path / "p"
    workspace.mkdir()

    m = WorkspaceManager(global_dir=str(global_dir))
    m.register_project(str(workspace), name="p")
    registry_path = global_dir / "projects.json"
    mtime_before = registry_path.stat().st_mtime_ns

    # Re-instantiate; should be a pure read.
    WorkspaceManager(global_dir=str(global_dir))
    assert registry_path.stat().st_mtime_ns == mtime_before
