import importlib.util
import asyncio
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "sandboxed-bullpen.py"


def load_module():
    spec = importlib.util.spec_from_file_location("sandboxed_bullpen_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sb(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "detect_supported_host", lambda: True)
    return module


def test_cli_requires_workspace_when_run_from_bullpen_root(sb, monkeypatch):
    monkeypatch.chdir(ROOT)

    with pytest.raises(sb.DeployError, match="Refusing to mount the Bullpen source checkout"):
        sb.config_from_args(["--admin-password", "pw", "--no-open"])


def test_cli_accepts_noninteractive_options(sb, tmp_path, monkeypatch):
    workspace = tmp_path / "project"
    home = tmp_path / "home"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)

    config = sb.config_from_args(
        [
            "--workspace",
            str(workspace),
            "--admin-password",
            "pw",
            "--sandbox-name",
            "testbox",
            "--bullpen-port",
            "8181",
            "--app-port",
            "3131",
            "--admin-user",
            "rootish",
            "--base",
            "test-base",
            "--sandbox-home",
            str(home),
            "--replace",
            "--no-open",
        ]
    )

    assert config.sandbox_name == "testbox"
    assert config.workspace == workspace.resolve()
    assert config.bullpen_port == 8181
    assert config.app_port == 3131
    assert config.admin_user == "rootish"
    assert config.admin_password == "pw"
    assert config.base == "test-base"
    assert config.sandbox_home == home.resolve()
    assert config.replace is True
    assert config.open_browser is False


def test_cli_rejects_duplicate_ports(sb, tmp_path, monkeypatch):
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(sb.DeployError, match="must be different"):
        sb.config_from_args(
            [
                "--workspace",
                str(workspace),
                "--admin-password",
                "pw",
                "--bullpen-port",
                "3000",
                "--app-port",
                "3000",
            ]
        )


def test_seed_credentials_skips_anthropic_key_when_claude_oauth_exists(sb, tmp_path, monkeypatch):
    host_home = tmp_path / "host"
    sandbox_home = tmp_path / "sandbox-home"
    workspace = tmp_path / "project"
    claude_dir = host_home / ".claude"
    claude_dir.mkdir(parents=True)
    workspace.mkdir()
    (claude_dir / ".credentials.json").write_text('{"claudeAiOauth":{"accessToken":"token"}}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "api-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(sb.shutil, "which", lambda _name: None)

    config = sb.config_from_args(
        [
            "--workspace",
            str(workspace),
            "--admin-password",
            "pw",
            "--sandbox-home",
            str(sandbox_home),
            "--no-open",
        ]
    )
    sb.build_runtime_env(config)
    summary = sb.seed_credentials(config)

    assert "OPENAI_API_KEY" in config.runtime_env
    assert "ANTHROPIC_API_KEY" not in config.runtime_env
    assert (sandbox_home / ".claude" / ".credentials.json").is_file()
    assert summary.provider_sources


def test_runtime_env_passes_microsandbox_label_to_server(sb, tmp_path, monkeypatch):
    workspace = tmp_path / "project"
    sandbox_home = tmp_path / "sandbox-home"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)

    config = sb.config_from_args(
        [
            "--workspace",
            str(workspace),
            "--admin-password",
            "pw",
            "--sandbox-name",
            "bullpen-3",
            "--sandbox-home",
            str(sandbox_home),
            "--no-open",
        ]
    )
    sb.build_runtime_env(config)

    assert config.runtime_env["BULLPEN_DEPLOY_LABEL"] == "(Microsandbox:bullpen-3)"


def test_seed_credentials_uses_existing_sandbox_codex_auth_when_host_mount_missing(sb, tmp_path, monkeypatch):
    host_home = tmp_path / "host"
    sandbox_home = tmp_path / "sandbox-home"
    workspace = tmp_path / "project"
    host_home.mkdir()
    workspace.mkdir()
    (sandbox_home / ".codex").mkdir(parents=True)
    (sandbox_home / ".codex" / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setattr(sb.shutil, "which", lambda _name: None)

    config = sb.config_from_args(
        [
            "--workspace",
            str(workspace),
            "--admin-password",
            "pw",
            "--sandbox-home",
            str(sandbox_home),
            "--no-open",
        ]
    )
    summary = sb.seed_credentials(config)

    assert f"home:{sandbox_home}/.codex/auth.json" in summary.provider_sources


def test_seed_credentials_syncs_host_codex_auth_by_default(sb, tmp_path, monkeypatch):
    host_home = tmp_path / "host"
    sandbox_home = tmp_path / "sandbox-home"
    workspace = tmp_path / "project"
    (host_home / ".codex").mkdir(parents=True)
    workspace.mkdir()
    (host_home / ".codex" / "auth.json").write_text('{"refresh_token":"host-token"}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(sb.shutil, "which", lambda _name: None)

    config = sb.config_from_args(
        [
            "--workspace",
            str(workspace),
            "--admin-password",
            "pw",
            "--sandbox-home",
            str(sandbox_home),
            "--no-open",
        ]
    )
    summary = sb.seed_credentials(config)

    assert (sandbox_home / ".codex" / "auth.json").read_text(encoding="utf-8") == '{"refresh_token":"host-token"}'
    assert f"home:{sandbox_home}/.codex/auth.json" in summary.provider_sources
    assert config.codex_auth_synced is True
    assert "env:OPENAI_API_KEY" in summary.provider_sources


def test_seed_credentials_syncs_host_claude_json_by_default(sb, tmp_path, monkeypatch):
    host_home = tmp_path / "host"
    sandbox_home = tmp_path / "sandbox-home"
    workspace = tmp_path / "project"
    host_home.mkdir()
    (host_home / ".claude").mkdir()
    workspace.mkdir()
    (host_home / ".claude.json").write_text('{"oauthAccount":"fresh"}', encoding="utf-8")
    (host_home / ".claude" / ".credentials.json").write_text(
        '{"claudeAiOauth":{"accessToken":"token"}}',
        encoding="utf-8",
    )
    (sandbox_home).mkdir(parents=True)
    (sandbox_home / ".claude.json").write_text('{"oauthAccount":"stale"}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(sb.shutil, "which", lambda _name: None)

    config = sb.config_from_args(
        [
            "--workspace",
            str(workspace),
            "--admin-password",
            "pw",
            "--sandbox-home",
            str(sandbox_home),
            "--no-open",
        ]
    )
    sb.seed_credentials(config)

    assert (sandbox_home / ".claude.json").read_text(encoding="utf-8") == '{"oauthAccount":"fresh"}'


def test_seed_credentials_uses_docker_home_claude_oauth_fallback(sb, tmp_path, monkeypatch):
    host_home = tmp_path / "host"
    docker_home = tmp_path / "docker-home"
    sandbox_home = tmp_path / "sandbox-home"
    workspace = tmp_path / "project"
    host_home.mkdir()
    workspace.mkdir()
    (host_home / ".claude.json").write_text('{"oauthAccount":"host"}', encoding="utf-8")
    (docker_home / ".claude").mkdir(parents=True)
    (sandbox_home / ".claude").mkdir(parents=True)
    (docker_home / ".claude.json").write_text('{"oauthAccount":"docker"}', encoding="utf-8")
    (docker_home / ".claude" / ".credentials.json").write_text('{"claudeAiOauth":{"accessToken":"docker"}}', encoding="utf-8")
    (sandbox_home / ".claude" / "stale-host-file").write_text("stale", encoding="utf-8")
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("BULLPEN_DOCKER_HOME", str(docker_home))
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(sb.shutil, "which", lambda _name: None)

    config = sb.config_from_args(
        [
            "--workspace",
            str(workspace),
            "--admin-password",
            "pw",
            "--sandbox-home",
            str(sandbox_home),
            "--no-open",
        ]
    )
    summary = sb.seed_credentials(config)

    assert (sandbox_home / ".claude" / ".credentials.json").read_text(encoding="utf-8") == '{"claudeAiOauth":{"accessToken":"docker"}}'
    assert (sandbox_home / ".claude.json").read_text(encoding="utf-8") == '{"oauthAccount":"docker"}'
    assert not (sandbox_home / ".claude" / "stale-host-file").exists()
    assert f"home:{sandbox_home}/.claude/.credentials.json" in summary.provider_sources


def test_seed_credentials_prefers_docker_claude_home_when_oauth_exists(sb, tmp_path, monkeypatch):
    host_home = tmp_path / "host"
    docker_home = tmp_path / "docker-home"
    sandbox_home = tmp_path / "sandbox-home"
    workspace = tmp_path / "project"
    (host_home / ".claude").mkdir(parents=True)
    (docker_home / ".claude").mkdir(parents=True)
    workspace.mkdir()
    (host_home / ".claude.json").write_text('{"oauthAccount":"host"}', encoding="utf-8")
    (docker_home / ".claude.json").write_text('{"oauthAccount":"docker"}', encoding="utf-8")
    (host_home / ".claude" / ".credentials.json").write_text('{"claudeAiOauth":{"accessToken":"host"}}', encoding="utf-8")
    (docker_home / ".claude" / ".credentials.json").write_text('{"claudeAiOauth":{"accessToken":"docker"}}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("BULLPEN_DOCKER_HOME", str(docker_home))
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(sb.shutil, "which", lambda _name: None)

    config = sb.config_from_args(
        [
            "--workspace",
            str(workspace),
            "--admin-password",
            "pw",
            "--sandbox-home",
            str(sandbox_home),
            "--no-open",
        ]
    )
    sb.seed_credentials(config)

    assert (sandbox_home / ".claude" / ".credentials.json").read_text(encoding="utf-8") == '{"claudeAiOauth":{"accessToken":"docker"}}'
    assert (sandbox_home / ".claude.json").read_text(encoding="utf-8") == '{"oauthAccount":"docker"}'


def test_seed_credentials_ignores_expired_docker_claude_oauth(sb, tmp_path, monkeypatch):
    host_home = tmp_path / "host"
    docker_home = tmp_path / "docker-home"
    sandbox_home = tmp_path / "sandbox-home"
    workspace = tmp_path / "project"
    (docker_home / ".claude").mkdir(parents=True)
    (sandbox_home / ".claude").mkdir(parents=True)
    workspace.mkdir()
    (docker_home / ".claude.json").write_text('{"oauthAccount":"docker"}', encoding="utf-8")
    (docker_home / ".claude" / ".credentials.json").write_text(
        '{"claudeAiOauth":{"accessToken":"expired","expiresAt":1}}',
        encoding="utf-8",
    )
    (sandbox_home / ".claude" / ".credentials.json").write_text(
        '{"claudeAiOauth":{"accessToken":"stale","expiresAt":1}}',
        encoding="utf-8",
    )
    (sandbox_home / ".claude.json").write_text('{"oauthAccount":"stale"}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("BULLPEN_DOCKER_HOME", str(docker_home))
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setattr(sb.shutil, "which", lambda _name: None)

    config = sb.config_from_args(
        [
            "--workspace",
            str(workspace),
            "--admin-password",
            "pw",
            "--sandbox-home",
            str(sandbox_home),
            "--no-open",
        ]
    )
    summary = sb.seed_credentials(config)

    assert (sandbox_home / ".claude").is_dir()
    assert not (sandbox_home / ".claude" / ".credentials.json").exists()
    assert not (sandbox_home / ".claude.json").exists()
    assert "env:OPENAI_API_KEY" in summary.provider_sources
    assert not any(".claude" in source for source in summary.provider_sources)


def test_runtime_env_disables_nested_codex_sandbox_like_docker(sb, tmp_path, monkeypatch):
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BULLPEN_CODEX_SANDBOX", raising=False)

    config = sb.config_from_args(
        [
            "--workspace",
            str(workspace),
            "--admin-password",
            "pw",
            "--no-open",
        ]
    )
    sb.build_runtime_env(config)

    assert config.runtime_env["BULLPEN_CODEX_SANDBOX"] == "none"
    assert config.runtime_env["BULLPEN_CODEX_PATH"] == "/home/bullpen/bin/codex"


def test_runtime_create_uses_expected_microsandbox_shape(sb, tmp_path, monkeypatch):
    calls = {}

    class FakeVolume:
        @staticmethod
        def bind(path, readonly=False):
            return {"path": path, "readonly": readonly}

    class FakeNetwork:
        @staticmethod
        def allow_all():
            return "allow-all"

    class FakeSandbox:
        @staticmethod
        def create(name, **kwargs):
            calls["name"] = name
            calls["kwargs"] = kwargs
            return types.SimpleNamespace()

    class FakeSnapshot:
        @staticmethod
        def get(name):
            return types.SimpleNamespace(name=name, path="/snapshots/bullpen-microsandbox-local")

    fake_module = types.SimpleNamespace(
        Sandbox=FakeSandbox,
        Snapshot=FakeSnapshot,
        Volume=FakeVolume,
        Network=FakeNetwork,
        is_installed=lambda: True,
    )
    monkeypatch.setitem(sys.modules, "microsandbox", fake_module)

    workspace = tmp_path / "project"
    sandbox_home = tmp_path / "home"
    workspace.mkdir()
    config = sb.DeployConfig(
        sandbox_name="testbox",
        workspace=workspace,
        bullpen_port=8081,
        app_port=3001,
        admin_user="admin",
        admin_password="pw",
        base="bullpen-microsandbox-local",
        sandbox_home=sandbox_home,
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=tmp_path / "project-default",
        runtime_env={"BULLPEN_PORT": "8081"},
    )

    sb.build_runtime_env(config)
    runtime = sb.MicrosandboxRuntime()
    asyncio.run(runtime.ensure_installed())
    asyncio.run(runtime.create(config))

    assert calls["name"] == "testbox"
    assert calls["kwargs"]["snapshot"] == "/snapshots/bullpen-microsandbox-local"
    assert "image" not in calls["kwargs"]
    assert calls["kwargs"]["replace"] is True
    assert calls["kwargs"]["detached"] is True
    assert calls["kwargs"]["ports"] == {8081: 8081, 3001: 3001}
    assert calls["kwargs"]["network"] == "allow-all"
    assert calls["kwargs"]["volumes"]["/app"] == {"path": str(ROOT), "readonly": True}
    assert calls["kwargs"]["volumes"]["/workspace"] == {"path": str(workspace), "readonly": False}
    assert calls["kwargs"]["volumes"]["/home/bullpen"] == {"path": str(sandbox_home), "readonly": False}
    assert "/home/bullpen/.codex" not in calls["kwargs"]["volumes"]
    assert calls["kwargs"]["env"]["BULLPEN_VENV"] == "/opt/bullpen-venv"


def test_host_port_preflight_reports_occupied_ports(sb, tmp_path, monkeypatch):
    workspace = tmp_path / "project"
    workspace.mkdir()
    config = sb.DeployConfig(
        sandbox_name="bullpen",
        workspace=workspace,
        bullpen_port=8080,
        app_port=3000,
        admin_user="admin",
        admin_password="pw",
        base="bullpen-microsandbox-local",
        sandbox_home=tmp_path / "home",
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=tmp_path / "project-default",
    )
    monkeypatch.setattr(sb, "host_port_in_use", lambda port: port == 8080)
    monkeypatch.setattr(sb, "host_port_owner", lambda port: f"COMMAND PID NAME\npython 123 *:{port}")

    with pytest.raises(sb.DeployError) as excinfo:
        sb.ensure_host_ports_available(config)

    assert "required host port(s) are occupied" in str(excinfo.value)
    assert "Port 8080 is already listening" in str(excinfo.value)
    assert "python 123" in str(excinfo.value)


def test_replace_existing_sandbox_stops_and_removes_before_port_check(sb, tmp_path, monkeypatch):
    calls = []

    class FakeRuntime:
        async def exists(self, name):
            calls.append(("exists", name))
            return True

        async def stop(self, name):
            calls.append(("stop", name))

        async def remove(self, name):
            calls.append(("remove", name))

    config = sb.DeployConfig(
        sandbox_name="bullpen",
        workspace=ROOT,
        bullpen_port=8080,
        app_port=3000,
        admin_user="admin",
        admin_password="pw",
        base="bullpen-microsandbox-local",
        sandbox_home=tmp_path / "home",
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=tmp_path / "project-default",
    )
    monkeypatch.setattr(sb, "wait_for_host_ports_available", lambda cfg: calls.append(("wait_ports", cfg.sandbox_name)))

    asyncio.run(sb.replace_existing_sandbox(FakeRuntime(), config))

    assert calls == [
        ("exists", "bullpen"),
        ("stop", "bullpen"),
        ("remove", "bullpen"),
        ("wait_ports", "bullpen"),
    ]


def test_replace_existing_sandbox_ignores_missing_sandbox(sb, tmp_path, monkeypatch):
    calls = []

    class FakeRuntime:
        async def exists(self, name):
            calls.append(("exists", name))
            return False

        async def stop(self, name):
            calls.append(("stop", name))

        async def remove(self, name):
            calls.append(("remove", name))

    config = sb.DeployConfig(
        sandbox_name="bullpen",
        workspace=ROOT,
        bullpen_port=8080,
        app_port=3000,
        admin_user="admin",
        admin_password="pw",
        base="bullpen-microsandbox-local",
        sandbox_home=tmp_path / "home",
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=tmp_path / "project-default",
    )
    monkeypatch.setattr(sb, "wait_for_host_ports_available", lambda _cfg: calls.append(("wait_ports",)))

    asyncio.run(sb.replace_existing_sandbox(FakeRuntime(), config))

    assert calls == [("exists", "bullpen")]


def test_detach_sandbox_requires_sdk_detach(sb):
    with pytest.raises(sb.DeployError, match="sandbox.detach"):
        asyncio.run(sb.detach_sandbox(types.SimpleNamespace()))


def test_detach_sandbox_calls_sdk_detach(sb):
    calls = []

    class FakeSandbox:
        async def detach(self):
            calls.append("detach")

    asyncio.run(sb.detach_sandbox(FakeSandbox()))

    assert calls == ["detach"]


def test_verify_detached_sandbox_requires_running_status(sb, monkeypatch):
    class FakeRuntime:
        async def status(self, _name):
            return "stopped"

    config = sb.DeployConfig(
        sandbox_name="bullpen",
        workspace=ROOT,
        bullpen_port=8080,
        app_port=3000,
        admin_user="admin",
        admin_password="pw",
        base="bullpen-microsandbox-local",
        sandbox_home=ROOT,
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=ROOT / "project",
    )
    monkeypatch.setattr(sb, "wait_for_health", lambda _port: None)

    with pytest.raises(sb.DeployError, match="not running after detach"):
        asyncio.run(sb.verify_detached_sandbox(FakeRuntime(), config))


def test_verify_detached_sandbox_checks_health_when_running(sb, monkeypatch):
    calls = []

    class FakeRuntime:
        async def status(self, _name):
            return "running"

    config = sb.DeployConfig(
        sandbox_name="bullpen",
        workspace=ROOT,
        bullpen_port=8080,
        app_port=3000,
        admin_user="admin",
        admin_password="pw",
        base="bullpen-microsandbox-local",
        sandbox_home=ROOT,
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=ROOT / "project",
    )
    monkeypatch.setattr(sb, "wait_for_health", lambda port: calls.append(port))

    asyncio.run(sb.verify_detached_sandbox(FakeRuntime(), config))

    assert calls == [8080]


def test_bullpen_start_and_verification_use_venv_python(sb):
    commands = []

    class FakeSandbox:
        def exec(self, cmd, args):
            commands.append((cmd, args))
            return types.SimpleNamespace(returncode=0)

    config = sb.DeployConfig(
        sandbox_name="bullpen",
        workspace=ROOT,
        bullpen_port=8080,
        app_port=3000,
        admin_user="admin",
        admin_password="pw",
        base="bullpen-microsandbox-local",
        sandbox_home=ROOT,
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=ROOT / "project",
    )
    sb.build_runtime_env(config)

    asyncio.run(sb.prepare_runtime_dirs(FakeSandbox(), config))
    asyncio.run(sb.bootstrap_bullpen_credentials(FakeSandbox(), config))
    asyncio.run(sb.start_bullpen(FakeSandbox(), config))
    asyncio.run(
        sb.verify_admin_credentials(
            FakeSandbox(),
            config,
        )
    )

    command_texts = [args[1] for _cmd, args in commands]
    prepare_command = command_texts[0]
    assert "useradd --uid" in prepare_command
    assert "BULLPEN_UID=" in prepare_command
    assert "Existing bullpen user has uid" in prepare_command
    assert "chown -R bullpen:\"$group_name\" /var/lib/bullpen" in prepare_command
    assert "chown -R bullpen:\"$group_name\" /home/bullpen" not in prepare_command
    assert "test -w /home/bullpen" in prepare_command
    assert any("BULLPEN_BOOTSTRAP_PASSWORD=pw" in command for command in command_texts)
    assert any("su -s /bin/bash bullpen -c" in command for command in command_texts)
    assert any("bullpen.py --bootstrap-credentials" in command for command in command_texts)
    start_command = next(command for command in command_texts if "nohup /opt/bullpen-venv/bin/python bullpen.py" in command)
    assert all(cmd == "bash" for cmd, _args in commands)
    assert "test -x /opt/bullpen-venv/bin/python" in start_command
    assert ": > /home/bullpen/logs/bullpen.log" in start_command
    assert "--host 0.0.0.0" in start_command
    assert any("cd /app && /opt/bullpen-venv/bin/python -" in command for command in command_texts)


def test_verify_mount_access_runs_as_bullpen_and_checks_workspace_config(sb):
    commands = []

    class FakeSandbox:
        def exec(self, cmd, args):
            commands.append((cmd, args))
            return types.SimpleNamespace(returncode=0)

    config = sb.DeployConfig(
        sandbox_name="bullpen",
        workspace=ROOT,
        bullpen_port=8080,
        app_port=3000,
        admin_user="admin",
        admin_password="pw",
        base="bullpen-microsandbox-local",
        sandbox_home=ROOT,
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=ROOT / "project",
    )
    sb.build_runtime_env(config)

    asyncio.run(sb.verify_mount_access(FakeSandbox(), config))

    repair_command = commands[0][1][1]
    probe_command = commands[1][1][1]
    assert 'chown -R "$uid:$gid" /workspace/.bullpen' in repair_command
    assert "su -s /bin/bash bullpen -c" in probe_command
    assert "test -r /workspace/.bullpen/config.json" in probe_command
    assert "test -w /workspace/.bullpen" in probe_command
    assert "effective user" not in probe_command
    assert "workspace metadata" not in probe_command


def test_run_sandbox_shell_raises_on_execoutput_exit_code(sb):
    class FakeSandbox:
        def exec(self, cmd, args):
            return types.SimpleNamespace(exit_code=127, success=False, stdout_text="", stderr_text="missing command")

    with pytest.raises(sb.DeployError, match="missing command"):
        asyncio.run(sb.run_sandbox_shell(FakeSandbox(), "missing-command"))


def test_install_codex_wrapper_uses_guest_local_codex_home_and_lock(sb):
    commands = []

    class FakeSandbox:
        def exec(self, cmd, args):
            commands.append((cmd, args))
            return types.SimpleNamespace(returncode=0)

    config = sb.DeployConfig(
        sandbox_name="bullpen",
        workspace=ROOT,
        bullpen_port=8080,
        app_port=3000,
        admin_user="admin",
        admin_password="pw",
        base="bullpen-microsandbox-local",
        sandbox_home=ROOT,
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=ROOT / "project",
    )
    sb.build_runtime_env(config)

    asyncio.run(sb.install_codex_wrapper(FakeSandbox(), config))

    command = commands[0][1][1]
    assert "cat > /home/bullpen/bin/codex" in command
    assert r'PERSISTENT_CODEX_HOME="\${BULLPEN_PERSISTENT_CODEX_HOME:-/home/bullpen/.codex}"' in command
    assert r'RUNTIME_CODEX_HOME="\${BULLPEN_CODEX_RUNTIME_HOME:-/var/lib/bullpen/codex-home}"' in command
    assert r'LOCK_DIR="\${BULLPEN_CODEX_LOCK_DIR:-/var/lib/bullpen/codex.lock}"' in command
    assert r'export CODEX_HOME="\$RUNTIME_CODEX_HOME"' in command
    assert r'cp -a "\$RUNTIME_CODEX_HOME"/. "\$PERSISTENT_CODEX_HOME"/' in command
    assert 'chown -R bullpen:"$(id -gn bullpen)" /var/lib/bullpen' in command
    assert 'chown -R bullpen:"$(id -gn bullpen)" /home/bullpen' not in command
    assert "test -w /home/bullpen/.codex" in command


def test_verify_codex_auth_runs_codex_exec_with_nested_sandbox_disabled(sb):
    commands = []

    class FakeSandbox:
        def exec(self, cmd, args):
            commands.append((cmd, args))
            return types.SimpleNamespace(returncode=0)

    config = sb.DeployConfig(
        sandbox_name="bullpen",
        workspace=ROOT,
        bullpen_port=8080,
        app_port=3000,
        admin_user="admin",
        admin_password="pw",
        base="bullpen-microsandbox-local",
        sandbox_home=ROOT,
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=ROOT / "project",
        codex_auth_synced=True,
    )
    sb.build_runtime_env(config)

    asyncio.run(sb.verify_codex_auth(FakeSandbox(), config))

    command = commands[0][1][1]
    assert "su -s /bin/bash bullpen -c" in command
    assert "test -f /home/bullpen/.codex/auth.json" in command
    assert "test -w /home/bullpen/.codex/auth.json" in command
    assert "for _attempt in 1 2" in command
    assert "timeout 45s bash -lc" in command
    assert "HOME=/home/bullpen BULLPEN_CODEX_SANDBOX=none" in command
    assert '"$BULLPEN_CODEX_PATH" exec --dangerously-bypass-approvals-and-sandbox --json --skip-git-repo-check -' in command


def test_configured_sandbox_shell_redacts_secret_values(sb):
    class FakeSandbox:
        def exec(self, cmd, args):
            return types.SimpleNamespace(exit_code=1, success=False, stdout_text="", stderr_text="bad secret-value")

    config = sb.DeployConfig(
        sandbox_name="bullpen",
        workspace=ROOT,
        bullpen_port=8080,
        app_port=3000,
        admin_user="admin",
        admin_password="secret-value",
        base="bullpen-microsandbox-local",
        sandbox_home=ROOT,
        replace=True,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=ROOT / "project",
        runtime_env={"BULLPEN_BOOTSTRAP_PASSWORD": "secret-value"},
    )

    with pytest.raises(sb.DeployError) as excinfo:
        asyncio.run(sb.run_configured_sandbox_shell(FakeSandbox(), config, "false", label="labeled failure"))

    assert "secret-value" not in str(excinfo.value)
    assert "[REDACTED]" in str(excinfo.value)
    assert "Sandbox command failed: labeled failure" in str(excinfo.value)
    assert "export BULLPEN_BOOTSTRAP_PASSWORD" not in str(excinfo.value)


def test_microsandbox_prepare_creates_local_snapshot_from_node_base():
    text = (ROOT / "deploy" / "microsandbox" / "prepare.sh").read_text(encoding="utf-8")

    assert 'SOURCE_IMAGE="${BULLPEN_MICROSANDBOX_SOURCE_IMAGE:-node:22-bookworm}"' in text
    assert 'BASE_NAME="${BULLPEN_MICROSANDBOX_BASE:-bullpen-microsandbox-local}"' in text
    assert "BULLPEN_MICROSANDBOX_SOURCE_DIR" in text
    assert 'git clone --depth 1 "${REPO_URL}" "${SOURCE_DIR}"' in text
    assert "microsandbox.Image.oci(source_image)" in text
    assert "microsandbox.Snapshot.create" in text
    assert "sandbox.stop_and_wait" in text
    assert text.index("sandbox.stop_and_wait") < text.index("microsandbox.Snapshot.create")
    assert "python3 -m venv /opt/bullpen-venv" in text
    assert "/opt/bullpen-venv/bin/python -m pip install --no-cache-dir -r /app/requirements.txt" in text
    assert "import pyfiglet" in text
    assert "@anthropic-ai/claude-code" in text
    assert "@openai/codex" in text
    assert "@google/gemini-cli" in text
    assert "--no-audit" in text
    assert "--no-fund" in text
    assert "--no-progress" in text
    assert "deb.nodesource.com" not in text


def test_choose_replace_no_replace_errors_when_existing(sb, monkeypatch):
    class FakeRuntime:
        async def exists(self, name):
            return True

    config = sb.DeployConfig(
        sandbox_name="bullpen",
        workspace=ROOT,
        bullpen_port=8080,
        app_port=3000,
        admin_user="admin",
        admin_password="pw",
        base="bullpen-microsandbox-local",
        sandbox_home=ROOT,
        replace=False,
        open_browser=False,
        install_bullpen_project=False,
        root=ROOT,
        bullpen_source=ROOT,
        github_repo_url="https://example.test/repo.git",
        local_project_path_default=ROOT / "project",
    )

    with pytest.raises(sb.DeployError, match="already exists"):
        asyncio.run(sb.choose_replace(FakeRuntime(), config))
