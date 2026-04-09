"""End-to-end tests for HTTP + Socket.IO authentication gating.

The test harness relies on the autouse ``_isolate_global_registry``
fixture in ``tests/conftest.py`` to patch ``server.workspace_manager.GLOBAL_DIR``
to a per-test throwaway directory. For each test that needs auth enabled
we write a ``.env`` file into that patched directory *before* calling
``create_app`` so the app picks up the credential.
"""

import os
import tempfile

import pytest

import server.workspace_manager as wm
from server import auth
from server.app import create_app, socketio


USERNAME = "admin"
PASSWORD = "correct horse"


def _seed_credentials(global_dir, username=USERNAME, password=PASSWORD):
    """Write credentials into the isolated global dir."""
    os.makedirs(global_dir, exist_ok=True)
    auth.write_env_file(
        auth.env_path(global_dir),
        {
            auth.USERNAME_KEY: username,
            auth.PASSWORD_HASH_KEY: auth.generate_password_hash(password),
        },
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_app(tmp_path):
    """Flask app with auth ENABLED via a seeded env file."""
    _seed_credentials(wm.GLOBAL_DIR)
    with tempfile.TemporaryDirectory(prefix="bullpen_auth_") as ws:
        app = create_app(ws, no_browser=True)
        yield app
    auth.reset_auth_cache()


@pytest.fixture
def auth_client(auth_app):
    return auth_app.test_client()


@pytest.fixture
def noauth_app(tmp_path):
    """Flask app with auth DISABLED (no env file written)."""
    # Sanity: the conftest fixture patched GLOBAL_DIR, and we do NOT seed.
    assert not os.path.exists(auth.env_path(wm.GLOBAL_DIR))
    with tempfile.TemporaryDirectory(prefix="bullpen_noauth_") as ws:
        app = create_app(ws, no_browser=True)
        yield app
    auth.reset_auth_cache()


@pytest.fixture
def noauth_client(noauth_app):
    return noauth_app.test_client()


def _login(client, username=USERNAME, password=PASSWORD):
    """Perform a full login flow; returns the POST response."""
    # Prime the session with a CSRF token.
    client.get("/login")
    with client.session_transaction() as sess:
        token = sess.get("csrf_token")
    return client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": token or "",
        },
    )


# ---------------------------------------------------------------------------
# Auth ENABLED — HTTP
# ---------------------------------------------------------------------------


class TestHttpAuthEnabled:
    def test_index_unauthenticated_redirects_to_login(self, auth_client):
        r = auth_client.get("/")
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]

    def test_login_page_accessible(self, auth_client):
        r = auth_client.get("/login")
        assert r.status_code == 200
        assert b"loginForm" in r.data

    def test_login_page_public_without_session(self, auth_client):
        # A fresh client with no cookies must still get the login page.
        r = auth_client.get("/login")
        assert r.status_code == 200

    def test_style_css_public(self, auth_client):
        # The login page needs its stylesheet to load without auth.
        r = auth_client.get("/style.css")
        assert r.status_code == 200

    def test_app_js_gated(self, auth_client):
        # Non-login static assets are gated.
        r = auth_client.get("/app.js")
        assert r.status_code == 302

    def test_login_success_redirects_to_index(self, auth_client):
        r = _login(auth_client)
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/")

    def test_login_sets_session(self, auth_client):
        _login(auth_client)
        with auth_client.session_transaction() as sess:
            assert sess.get("authenticated") is True
            assert sess.get("username") == USERNAME

    def test_login_failure_wrong_password(self, auth_client):
        r = _login(auth_client, password="nope")
        assert r.status_code == 302
        assert "error=1" in r.headers["Location"]
        with auth_client.session_transaction() as sess:
            assert sess.get("authenticated") is not True

    def test_login_failure_wrong_username(self, auth_client):
        r = _login(auth_client, username="eve")
        assert r.status_code == 302
        assert "error=1" in r.headers["Location"]

    def test_login_csrf_invalid(self, auth_client):
        # Submit without a valid CSRF token.
        r = auth_client.post(
            "/login",
            data={"username": USERNAME, "password": PASSWORD, "csrf_token": "bogus"},
        )
        assert r.status_code == 302
        assert "error=csrf" in r.headers["Location"]

    def test_logout_clears_session(self, auth_client):
        _login(auth_client)
        r = auth_client.get("/logout")
        assert r.status_code == 302
        with auth_client.session_transaction() as sess:
            assert sess.get("authenticated") is not True

    def test_api_files_unauthenticated_returns_401_when_xhr(self, auth_client):
        r = auth_client.get(
            "/api/files",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert r.status_code == 401

    def test_api_files_unauthenticated_redirects_when_browser(self, auth_client):
        r = auth_client.get("/api/files")
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]

    def test_file_write_unauthenticated_rejected(self, auth_client):
        r = auth_client.put(
            "/api/files/foo.txt",
            data="hi",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert r.status_code == 401

    def test_next_param_preserved(self, auth_client):
        r = auth_client.get("/")
        loc = r.headers["Location"]
        assert "next=/" in loc

    def test_authenticated_can_hit_api(self, auth_client):
        _login(auth_client)
        r = auth_client.get("/api/files")
        assert r.status_code == 200

    def test_authenticated_index_200(self, auth_client):
        _login(auth_client)
        r = auth_client.get("/")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Auth ENABLED — Socket.IO
# ---------------------------------------------------------------------------


class TestSocketIoAuthEnabled:
    def test_socketio_connect_unauthenticated_rejected(self, auth_app):
        # No session cookie → server should reject the connect.
        client = socketio.test_client(auth_app)
        assert client.is_connected() is False

    def test_socketio_connect_authenticated_accepted(self, auth_app):
        # Perform a real login via the Flask test client to obtain a
        # session cookie, then use flask_test_client= to share that
        # cookie jar with the Socket.IO test client.
        http = auth_app.test_client()
        _login(http)
        sio_client = socketio.test_client(auth_app, flask_test_client=http)
        assert sio_client.is_connected() is True
        events = sio_client.get_received()
        names = [e["name"] for e in events]
        assert "state:init" in names
        sio_client.disconnect()


# ---------------------------------------------------------------------------
# Auth DISABLED — everything should just work
# ---------------------------------------------------------------------------


class TestAuthDisabled:
    def test_no_auth_index_accessible(self, noauth_client):
        r = noauth_client.get("/")
        assert r.status_code == 200

    def test_no_auth_api_files(self, noauth_client):
        r = noauth_client.get("/api/files")
        assert r.status_code == 200

    def test_no_auth_login_page_redirects_to_index(self, noauth_client):
        # With auth disabled there is no login page — /login bounces
        # the user to the app.
        r = noauth_client.get("/login")
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/")

    def test_no_auth_socketio_connects(self, noauth_app):
        client = socketio.test_client(noauth_app)
        assert client.is_connected() is True
        client.disconnect()
