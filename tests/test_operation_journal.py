import os
import subprocess
import sys
import time

from server.app import create_app
from server.init import init_workspace
from server.operation_journal import (
    begin_operation,
    mark_operation_committed,
    recover_pending_operations,
)
from server.persistence import read_json, write_json


ROOT = os.path.dirname(os.path.dirname(__file__))


def test_prepared_operation_recovers_after_process_exit(tmp_path):
    bp_dir = tmp_path / ".bullpen"
    bp_dir.mkdir()
    layout_path = bp_dir / "layout.json"
    profile_path = bp_dir / "profiles" / "new-profile.json"
    write_json(str(layout_path), {"slots": [{"name": "Before"}]})
    script = f"""
import os
from server.operation_journal import begin_operation
from server.persistence import read_json, write_json
bp_dir = {str(bp_dir)!r}
layout_path = {str(layout_path)!r}
profile_path = {str(profile_path)!r}
begin_operation(
    bp_dir,
    kind="crash-probe",
    restore_files=[
        {{"path": layout_path, "content": read_json(layout_path)}},
        {{"path": profile_path, "content": None}},
    ],
)
write_json(layout_path, {{"slots": [{{"name": "After"}}]}})
write_json(profile_path, {{"id": "new-profile"}})
os._exit(17)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 17

    recovered = recover_pending_operations([str(bp_dir)])

    assert recovered
    assert read_json(str(layout_path)) == {"slots": [{"name": "Before"}]}
    assert not profile_path.exists()


def test_committed_operation_survives_cleanup_recovery(tmp_path):
    bp_dir = tmp_path / ".bullpen"
    bp_dir.mkdir()
    layout_path = bp_dir / "layout.json"
    write_json(str(layout_path), {"slots": [{"name": "Before"}]})
    operation_path = begin_operation(
        str(bp_dir),
        kind="commit-probe",
        restore_files=[{"path": str(layout_path), "content": read_json(str(layout_path))}],
    )
    write_json(str(layout_path), {"slots": [{"name": "After"}]})
    mark_operation_committed(operation_path)

    recover_pending_operations([str(bp_dir)])

    assert read_json(str(layout_path)) == {"slots": [{"name": "After"}]}
    assert not os.path.exists(operation_path)


def test_nested_operations_recover_newest_before_enclosing_group(tmp_path):
    bp_dir = tmp_path / ".bullpen"
    bp_dir.mkdir()
    layout_path = bp_dir / "layout.json"
    original = {"slots": [{"name": "Original"}]}
    intermediate = {"slots": [{"name": "First member"}]}
    final = {"slots": [{"name": "Second member"}]}
    write_json(str(layout_path), original)
    begin_operation(
        str(bp_dir),
        kind="group",
        restore_files=[{"path": str(layout_path), "content": original}],
    )
    write_json(str(layout_path), intermediate)
    time.sleep(0.01)
    begin_operation(
        str(bp_dir),
        kind="member",
        restore_files=[{"path": str(layout_path), "content": intermediate}],
    )
    write_json(str(layout_path), final)

    recover_pending_operations([str(bp_dir)])

    assert read_json(str(layout_path)) == original


def test_application_startup_recovers_prepared_workspace_operation(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bp_dir = init_workspace(str(workspace))
    layout_path = os.path.join(bp_dir, "layout.json")
    original = read_json(layout_path)
    operation_path = begin_operation(
        bp_dir,
        kind="startup-probe",
        restore_files=[{"path": layout_path, "content": original}],
    )
    write_json(layout_path, {"slots": [{"name": "Interrupted"}]})

    create_app(
        str(workspace),
        no_browser=True,
        global_dir=str(tmp_path / "global"),
    )

    recovered = read_json(layout_path)
    assert recovered["slots"] == original["slots"]
    assert all(slot is None or slot.get("name") != "Interrupted" for slot in recovered["slots"])
    assert not os.path.exists(operation_path)
