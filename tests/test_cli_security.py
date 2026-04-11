"""CLI startup security checks."""

import pytest

import bullpen
from server import auth


def test_require_auth_for_network_bind_rejects_wildcard_without_password(tmp_path, monkeypatch):
    monkeypatch.setattr("server.workspace_manager.GLOBAL_DIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="refusing to bind to '0.0.0.0'"):
        bullpen.require_auth_for_network_bind("0.0.0.0")


def test_require_auth_for_network_bind_allows_loopback_without_password(tmp_path, monkeypatch):
    monkeypatch.setattr("server.workspace_manager.GLOBAL_DIR", str(tmp_path))

    bullpen.require_auth_for_network_bind("127.0.0.1")
    bullpen.require_auth_for_network_bind("localhost")
    bullpen.require_auth_for_network_bind("::1")


def test_require_auth_for_network_bind_allows_network_bind_with_password(tmp_path, monkeypatch):
    monkeypatch.setattr("server.workspace_manager.GLOBAL_DIR", str(tmp_path))
    auth.write_env_file(
        auth.env_path(str(tmp_path)),
        {
            auth.USERNAME_KEY: "admin",
            auth.PASSWORD_HASH_KEY: auth.generate_password_hash("hunter2"),
        },
    )

    bullpen.require_auth_for_network_bind("0.0.0.0")
