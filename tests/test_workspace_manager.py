"""Tests for workspace manager project registry lifecycle."""

import os

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
