"""Tests for commit and diff socket events."""

import subprocess

from server.app import create_app, socketio


def _git(ws, *args):
    return subprocess.run(
        ["git", *args],
        cwd=ws,
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(ws):
    _git(ws, "init")
    _git(ws, "config", "user.name", "Test User")
    _git(ws, "config", "user.email", "test@example.com")
    with open(f"{ws}/sample.txt", "w", encoding="utf-8") as f:
        f.write("line one\n")
    _git(ws, "add", "sample.txt")
    _git(ws, "commit", "-m", "initial")
    with open(f"{ws}/sample.txt", "a", encoding="utf-8") as f:
        f.write("line two\n")
    _git(ws, "add", "sample.txt")
    _git(ws, "commit", "-m", "second")


def _received(client, name):
    for event in client.get_received():
        if event["name"] == name:
            return event["args"][0]
    return None


def test_commit_diff_returns_patch(tmp_workspace):
    _init_repo(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    commit_hash = _git(tmp_workspace, "rev-parse", "HEAD").stdout.strip()
    client.emit("commits:diff", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "diff-one",
        "hash": commit_hash,
    })

    body = _received(client, "commits:diffed")
    assert body is not None
    assert body["request_id"] == "diff-one"
    assert body["hash"] == commit_hash
    assert "diff --git" in body["diff"]
    assert "+line two" in body["diff"]
    client.disconnect()


def test_commit_diff_rejects_invalid_hash(tmp_workspace):
    _init_repo(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("commits:diff", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "diff-bad",
        "hash": "not-a-hash",
    })

    body = _received(client, "commits:error")
    assert body is not None
    assert body["request_id"] == "diff-bad"
    assert body["error"] == "Invalid commit hash"
    client.disconnect()


def test_commit_list_returns_page(tmp_workspace):
    _init_repo(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("commits:list", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "list-one",
        "offset": 0,
        "count": 1,
    })

    body = _received(client, "commits:listed")
    assert body is not None
    assert body["request_id"] == "list-one"
    assert len(body["commits"]) == 1
    assert body["has_more"] is True
    assert body["total"] >= 2
    client.disconnect()


def test_git_status_returns_branch_and_changes(tmp_workspace):
    _init_repo(tmp_workspace)
    with open(f"{tmp_workspace}/sample.txt", "a", encoding="utf-8") as f:
        f.write("dirty\n")
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("git:status", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "status-one",
    })

    body = _received(client, "git:statused")
    assert body is not None
    assert body["request_id"] == "status-one"
    assert body["clean"] is False
    assert body["changes"]
    assert "sample.txt" in "\n".join(body["changes"])
    client.disconnect()


def test_git_branch_diff_returns_current_branch_diff(tmp_workspace):
    _init_repo(tmp_workspace)
    _git(tmp_workspace, "checkout", "-b", "feature")
    with open(f"{tmp_workspace}/feature.txt", "w", encoding="utf-8") as f:
        f.write("feature\n")
    _git(tmp_workspace, "add", "feature.txt")
    _git(tmp_workspace, "commit", "-m", "feature")
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("git:branch-diff", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "branch-diff-one",
    })

    body = _received(client, "git:branch-diffed")
    assert body is not None
    assert body["request_id"] == "branch-diff-one"
    assert body["branch"] == "feature"
    assert "diff --git" in body["diff"]
    assert "feature.txt" in body["diff"]
    client.disconnect()


def test_git_action_rejects_unsupported_command(tmp_workspace):
    _init_repo(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("git:action", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "action-bad",
        "action": "reset-hard",
    })

    body = _received(client, "git:error")
    assert body is not None
    assert body["request_id"] == "action-bad"
    assert body["error"] == "Unsupported git command"
    client.disconnect()


def test_commit_rest_routes_are_removed(tmp_workspace):
    _init_repo(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)

    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/commits" not in routes
    assert "/api/commits/<commit_hash>/diff" not in routes
