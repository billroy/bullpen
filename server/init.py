"""First-time .bullpen/ initialization."""

import os
import shutil

from server.persistence import write_json, atomic_write


DEFAULT_CONFIG = {
    "name": "Bullpen",
    "theme": "dark",
    "grid": {"rows": 4, "cols": 6},
    "columns": [
        {"key": "inbox", "label": "Inbox", "color": "#6B7280"},
        {"key": "assigned", "label": "Assigned", "color": "#3B82F6"},
        {"key": "in_progress", "label": "In Progress", "color": "#8B5CF6"},
        {"key": "review", "label": "Review", "color": "#F59E0B"},
        {"key": "done", "label": "Done", "color": "#10B981"},
        {"key": "blocked", "label": "Blocked", "color": "#EF4444"},
    ],
    "agent_timeout_seconds": 600,
    "max_prompt_chars": 100000,
}

DEFAULT_LAYOUT = {"slots": []}


def init_workspace(workspace):
    """Create .bullpen/ directory structure. Idempotent."""
    bp = os.path.join(workspace, ".bullpen")

    # Create directories
    for d in ["tasks", "profiles", "teams", "logs"]:
        os.makedirs(os.path.join(bp, d), exist_ok=True)

    # .gitignore for logs
    gitignore_path = os.path.join(bp, ".gitignore")
    if not os.path.exists(gitignore_path):
        atomic_write(gitignore_path, "logs/\n")

    # config.json — only create if missing
    config_path = os.path.join(bp, "config.json")
    if not os.path.exists(config_path):
        write_json(config_path, DEFAULT_CONFIG)

    # layout.json — only create if missing
    layout_path = os.path.join(bp, "layout.json")
    if not os.path.exists(layout_path):
        write_json(layout_path, DEFAULT_LAYOUT)

    # Prompt files — only create if missing
    for name in ["workspace_prompt.md", "bullpen_prompt.md"]:
        path = os.path.join(bp, name)
        if not os.path.exists(path):
            atomic_write(path, "")

    # Copy default profiles if profiles dir is empty
    profiles_dir = os.path.join(bp, "profiles")
    if not os.listdir(profiles_dir):
        src_profiles = os.path.join(os.path.dirname(os.path.dirname(__file__)), "profiles")
        if os.path.isdir(src_profiles):
            for f in os.listdir(src_profiles):
                if f.endswith(".json"):
                    shutil.copy2(os.path.join(src_profiles, f), profiles_dir)

    return bp
