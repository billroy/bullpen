"""Shared Bullpen MCP configuration helpers for agent adapters."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

from server import mcp_tools
from server.persistence import read_json


TOOL_PROFILES = {
    "read": {
        "list_tickets",
        "list_tasks",
        "list_tickets_by_title",
        "list_values",
        "get_value",
    },
    "ticket-write": {
        "list_tickets",
        "list_tasks",
        "list_tickets_by_title",
        "create_ticket",
        "update_ticket",
    },
    "interactive": {
        "list_tickets",
        "list_tasks",
        "list_tickets_by_title",
        "list_values",
        "get_value",
        "set_value",
        "increment_value",
        "decrement_value",
        "speak_text",
    },
}


@dataclass(frozen=True)
class BullpenMcpServerSpec:
    command: str
    args: list[str]
    cwd: str
    env: dict[str, str]
    tool_names: list[str]


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def all_tool_names() -> list[str]:
    return [tool["name"] for tool in mcp_tools.TOOLS]


def tool_names(profile: str = "all") -> list[str]:
    if profile == "all":
        return all_tool_names()
    wanted = TOOL_PROFILES.get(profile)
    if wanted is None:
        raise ValueError(f"Unknown Bullpen MCP tool profile: {profile}")
    return [name for name in all_tool_names() if name in wanted]


def bullpen_mcp_server_spec(bp_dir: str, *, tool_profile: str = "all") -> BullpenMcpServerSpec:
    root = project_root()
    server_script = os.path.join(root, "server", "mcp_tools.py")
    bp_dir = os.path.abspath(bp_dir)

    bp_config = read_json(os.path.join(bp_dir, "config.json"))
    host = bp_config.get("server_host", "127.0.0.1")
    if host == "0.0.0.0":
        host = "127.0.0.1"
    port = str(bp_config.get("server_port", 5000))

    return BullpenMcpServerSpec(
        command=sys.executable,
        args=[server_script, "--bp-dir", bp_dir, "--host", host, "--port", port],
        cwd=root,
        env={"PYTHONPATH": root},
        tool_names=tool_names(tool_profile),
    )


def claude_mcp_config(bp_dir: str) -> dict:
    spec = bullpen_mcp_server_spec(bp_dir)
    return {
        "mcpServers": {
            "bullpen": {
                "command": spec.command,
                "args": spec.args,
                "env": spec.env,
            },
        },
    }


def codex_mcp_overrides(bp_dir: str) -> list[str]:
    spec = bullpen_mcp_server_spec(bp_dir)
    return [
        "-c", f"mcp_servers.bullpen.command={json.dumps(spec.command)}",
        "-c", f"mcp_servers.bullpen.args={json.dumps(spec.args)}",
        "-c", f"mcp_servers.bullpen.cwd={json.dumps(spec.cwd)}",
        "-c", f"mcp_servers.bullpen.env.PYTHONPATH={json.dumps(spec.env['PYTHONPATH'])}",
        "-c", "mcp_servers.bullpen.default_tools_approval_mode=\"approve\"",
        "-c", "mcp_servers.bullpen.tool_timeout_sec=120",
    ]


def opencode_mcp_config(bp_dir: str, *, launcher_path: str | None = None) -> dict:
    spec = bullpen_mcp_server_spec(bp_dir)
    # OpenCode bootstraps project config for paths it sees in local MCP command
    # definitions and environment. Avoid exposing the Bullpen source tree in
    # either place; the adapter supplies a temp launcher that imports the helper.
    mcp_cwd = os.path.abspath(bp_dir)
    if launcher_path:
        command = [spec.command, os.path.abspath(launcher_path), *spec.args[1:]]
        environment = {}
    else:
        command = [spec.command, "-m", "server.mcp_tools", *spec.args[1:]]
        environment = spec.env
    return {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "bullpen": {
                "type": "local",
                "enabled": True,
                "command": command,
                "cwd": mcp_cwd,
                "environment": environment,
            },
        },
    }


def antigravity_mcp_config(bp_dir: str, *, tool_profile: str = "all") -> dict:
    spec = bullpen_mcp_server_spec(bp_dir, tool_profile=tool_profile)
    return {
        "mcpServers": {
            "bullpen": {
                "command": spec.command,
                "args": spec.args,
                "cwd": spec.cwd,
                "env": spec.env,
                "enabledTools": spec.tool_names,
            },
        },
    }
