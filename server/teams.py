"""Team save/load."""

import os

from server.persistence import read_json, write_json


def _teams_dir(bp_dir):
    return os.path.join(bp_dir, "teams")


def save_team(bp_dir, name, layout):
    """Save current layout as a named team. Strips task_queue from slots."""
    team_layout = {"slots": []}
    for slot in layout.get("slots", []):
        if slot is None:
            team_layout["slots"].append(None)
        else:
            # Copy slot but exclude runtime state
            saved = {k: v for k, v in slot.items() if k not in ("task_queue", "state")}
            team_layout["slots"].append(saved)

    path = os.path.join(_teams_dir(bp_dir), f"{name}.json")
    write_json(path, team_layout)
    return team_layout


def load_team(bp_dir, name):
    """Load a named team. Returns layout dict or None."""
    path = os.path.join(_teams_dir(bp_dir), f"{name}.json")
    if not os.path.exists(path):
        return None
    team = read_json(path)
    # Re-add runtime fields
    for slot in team.get("slots", []):
        if slot is not None:
            slot.setdefault("task_queue", [])
            slot.setdefault("state", "idle")
    return team


def list_teams(bp_dir):
    """List saved team names."""
    teams_dir = _teams_dir(bp_dir)
    if not os.path.isdir(teams_dir):
        return []
    return sorted(
        f[:-5] for f in os.listdir(teams_dir) if f.endswith(".json")
    )
