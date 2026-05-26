import pytest

import server.manager as manager_mod
from server.manager import (
    ManagerError,
    PortAllocator,
    ProfileRegistry,
    create_manager_app,
    create_profile,
)


def test_create_profile_allocates_ports_and_persists(tmp_path):
    registry = ProfileRegistry(tmp_path / "manager")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "bullpen.py").write_text("", encoding="utf-8")

    profile = create_profile(
        registry,
        {
            "displayName": "Local Dev",
            "workspaceRoot": str(workspace),
            "bullpenSource": str(source),
        },
    )

    assert profile["id"] == "local-dev"
    assert profile["runtime"] == "local"
    assert profile["ports"] == {"bullpen": 8080, "app": 3000}
    assert profile["portReservation"]["owner"] == "local-dev"
    assert registry.get("local-dev")["workspaceRoot"] == str(workspace)


def test_port_allocator_skips_reserved_and_listening_ports(tmp_path, monkeypatch):
    registry = ProfileRegistry(tmp_path / "manager")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "bullpen.py").write_text("", encoding="utf-8")
    create_profile(
        registry,
        {
            "displayName": "First",
            "workspaceRoot": str(workspace),
            "bullpenSource": str(source),
        },
    )
    monkeypatch.setattr(manager_mod, "is_port_listening", lambda port, *args, **kwargs: int(port) == 8081)
    allocator = PortAllocator(registry, bullpen_range=(8081, 8083), app_range=(3001, 3003))
    allocated = allocator.allocate()
    assert allocated == {"bullpen": 8082, "app": 3002}


def test_create_profile_rejects_unimplemented_runtime(tmp_path):
    registry = ProfileRegistry(tmp_path / "manager")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ManagerError, match="not implemented"):
        create_profile(
            registry,
            {
                "displayName": "Sandbox",
                "runtime": "microsandbox",
                "workspaceRoot": str(workspace),
            },
        )


def test_manager_api_create_profile(tmp_path):
    home = tmp_path / "manager"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "bullpen.py").write_text("", encoding="utf-8")
    app, _socketio = create_manager_app(home=home)

    client = app.test_client()
    response = client.post(
        "/api/profiles",
        json={
            "displayName": "API Instance",
            "workspaceRoot": str(workspace),
            "bullpenSource": str(source),
        },
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["profile"]["id"] == "api-instance"
    assert data["profile"]["ports"]["bullpen"] == 8080

    list_response = client.get("/api/profiles")
    assert list_response.status_code == 200
    assert list_response.get_json()["profiles"][0]["id"] == "api-instance"


def test_local_runtime_builds_bullpen_command(tmp_path):
    from server.manager import LocalRuntimeController

    registry = ProfileRegistry(tmp_path / "manager")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "bullpen.py").write_text("", encoding="utf-8")
    profile = create_profile(
        registry,
        {
            "displayName": "Command",
            "workspaceRoot": str(workspace),
            "bullpenSource": str(source),
        },
    )

    argv = LocalRuntimeController(registry).build_argv(profile)

    assert argv[1] == str(source / "bullpen.py")
    assert "--workspace" in argv
    assert str(workspace) in argv
    assert "--no-browser" in argv


def test_local_runtime_start_sets_desired_state(tmp_path, monkeypatch):
    from server.manager import LocalRuntimeController

    class FakeProcess:
        pid = 4242

        def poll(self):
            return None

    registry = ProfileRegistry(tmp_path / "manager")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "bullpen.py").write_text("", encoding="utf-8")
    profile = create_profile(
        registry,
        {
            "displayName": "Start Me",
            "workspaceRoot": str(workspace),
            "bullpenSource": str(source),
        },
    )
    monkeypatch.setattr(manager_mod, "is_port_listening", lambda *args, **kwargs: False)
    monkeypatch.setattr(manager_mod, "wait_for_http_health", lambda *args, **kwargs: True)
    monkeypatch.setattr(manager_mod.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    started = LocalRuntimeController(registry).start(profile["id"])

    assert started["desiredState"] == "running"
    assert started["observed"]["state"] == "healthy"
    assert registry.get(profile["id"])["desiredState"] == "running"
