"""Regression guards for the no-REST application architecture."""

from server.app import create_app
from server.init import init_workspace
from server.manager import create_manager_app


def _api_routes(app):
    return sorted(rule.rule for rule in app.url_map.iter_rules() if rule.rule.startswith("/api/"))


def test_main_app_registers_no_api_routes(tmp_workspace):
    init_workspace(tmp_workspace)
    app = create_app(tmp_workspace, no_browser=True)

    assert _api_routes(app) == []


def test_manager_app_registers_no_api_routes(tmp_path):
    app, _socketio = create_manager_app(home=tmp_path / "manager")

    assert _api_routes(app) == []
