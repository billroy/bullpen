"""Helpers for workspace-scoped MCP authentication metadata."""

from __future__ import annotations

import os
import secrets

from server.persistence import read_json, write_json


def _config_path(bp_dir):
    return os.path.join(bp_dir, "config.json")


def _normalize_token(value):
    if not isinstance(value, str):
        return None
    token = value.strip()
    return token or None


def read_workspace_mcp_token(bp_dir):
    """Return the stored MCP token for a workspace, if any."""
    try:
        config = read_json(_config_path(bp_dir))
    except Exception:
        return None
    return _normalize_token(config.get("mcp_token"))


def _generate_unique_token(disallowed_tokens=None):
    disallowed = set(disallowed_tokens or ())
    while True:
        token = secrets.token_urlsafe(32)
        if token not in disallowed:
            return token


def ensure_workspace_runtime_config(bp_dir, host=None, port=None, disallowed_tokens=None, preferred_token=None):
    """Stamp runtime connection metadata into a workspace config.

    Returns the workspace's MCP token, generating a fresh one when missing or
    when it would collide with another active workspace token.
    """
    config = read_json(_config_path(bp_dir))
    token = _normalize_token(preferred_token) or _normalize_token(config.get("mcp_token"))
    blocked = set(disallowed_tokens or ())
    if not token or token in blocked:
        token = _generate_unique_token(blocked)
    if host is not None:
        config["server_host"] = host
    if port is not None:
        config["server_port"] = port
    config["mcp_token"] = token
    write_json(_config_path(bp_dir), config)
    return token


def initialize_workspace_runtime_configs(workspaces, host, port):
    """Ensure every active workspace has distinct runtime MCP metadata."""
    tokens_by_workspace = {}
    used_tokens = set()
    for ws in workspaces:
        token = ensure_workspace_runtime_config(
            ws.bp_dir,
            host=host,
            port=port,
            disallowed_tokens=used_tokens,
        )
        tokens_by_workspace[ws.id] = token
        used_tokens.add(token)
    return tokens_by_workspace


def workspace_token_set(workspaces, exclude_bp_dir=None):
    """Return the set of non-empty workspace tokens for the given workspaces."""
    excluded = os.path.realpath(exclude_bp_dir) if exclude_bp_dir else None
    tokens = set()
    for ws in workspaces:
        bp_dir = getattr(ws, "bp_dir", ws)
        if excluded and os.path.realpath(bp_dir) == excluded:
            continue
        token = read_workspace_mcp_token(bp_dir)
        if token:
            tokens.add(token)
    return tokens


def find_workspace_id_for_token(workspaces, token):
    """Resolve a workspace ID for the provided token.

    Returns ``None`` when the token is missing, invalid, or ambiguously shared
    by more than one workspace.
    """
    normalized = _normalize_token(token)
    if not normalized:
        return None
    matches = []
    for ws in workspaces:
        if read_workspace_mcp_token(ws.bp_dir) == normalized:
            matches.append(ws.id)
            if len(matches) > 1:
                return None
    return matches[0] if matches else None


def rotate_workspace_mcp_token(bp_dir, host=None, port=None, disallowed_tokens=None):
    """Rotate a workspace MCP token and persist the updated runtime config."""
    blocked = set(disallowed_tokens or ())
    current = read_workspace_mcp_token(bp_dir)
    if current:
        blocked.add(current)
    token = _generate_unique_token(blocked)
    config = read_json(_config_path(bp_dir))
    config["mcp_token"] = token
    if host is not None:
        config["server_host"] = host
    if port is not None:
        config["server_port"] = port
    write_json(_config_path(bp_dir), config)
    return token
