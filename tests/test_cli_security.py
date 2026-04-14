"""CLI startup security checks."""

import builtins

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


def test_parse_args_accepts_multiple_set_password_and_delete_user():
    args = bullpen.parse_args(
        [
            "--set-password",
            "admin",
            "--set-password",
            "alice",
            "--delete-user",
            "legacy",
        ]
    )
    assert args.set_password == ["admin", "alice"]
    assert args.delete_user == ["legacy"]


def test_parse_args_websocket_debug_defaults_false():
    args = bullpen.parse_args([])
    assert args.websocket_debug is False


def test_parse_args_supports_websocket_debug():
    args = bullpen.parse_args(["--websocket-debug"])
    assert args.websocket_debug is True


def test_set_password_cli_add_and_delete_users(tmp_path, monkeypatch):
    monkeypatch.setattr("server.workspace_manager.GLOBAL_DIR", str(tmp_path))
    existing = auth.apply_credentials_mapping(
        {},
        {"old": auth.generate_password_hash("oldpw")},
    )
    auth.write_env_file(auth.env_path(str(tmp_path)), existing)

    prompts = iter(["newpass", "newpass"])

    def fake_getpass(_prompt):
        return next(prompts)

    monkeypatch.setattr("getpass.getpass", fake_getpass)
    monkeypatch.setattr(builtins, "input", lambda _p: "ignored")

    rc = bullpen.set_password_cli(set_usernames=["new"], delete_usernames=["old"])
    assert rc == 0

    auth.reset_auth_cache()
    auth.load_credentials(str(tmp_path))
    users = auth.get_users()
    assert "new" in users
    assert "old" not in users


def test_bootstrap_credentials_force_updates_existing_user(tmp_path, monkeypatch):
    monkeypatch.setattr("server.workspace_manager.GLOBAL_DIR", str(tmp_path))
    existing = auth.apply_credentials_mapping(
        {},
        {"admin": auth.generate_password_hash("oldpass")},
    )
    auth.write_env_file(auth.env_path(str(tmp_path)), existing)

    monkeypatch.setenv("BULLPEN_BOOTSTRAP_USER", "admin")
    monkeypatch.setenv("BULLPEN_BOOTSTRAP_PASSWORD", "newpass")
    monkeypatch.setenv("BULLPEN_BOOTSTRAP_FORCE", "1")

    rc = bullpen.bootstrap_credentials()
    assert rc == 0

    auth.reset_auth_cache()
    auth.load_credentials(str(tmp_path))
    assert auth.check_password("newpass", auth.get_password_hash("admin"))
    assert not auth.check_password("oldpass", auth.get_password_hash("admin"))
