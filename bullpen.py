#!/usr/bin/env python3
"""Bullpen — AI agent team manager."""

import argparse
import os
import sys


LOCALHOST_BINDS = {"127.0.0.1", "localhost", "::1"}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="bullpen",
        description="Bullpen — manage a team of AI coding agents",
    )
    parser.add_argument(
        "--workspace",
        default=os.getcwd(),
        help="Path to the workspace directory (default: current directory)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port to serve on (default: 5000)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open a browser on startup",
    )
    parser.add_argument(
        "--set-password",
        action="store_true",
        help=(
            "Interactively set the Bullpen login username and password. "
            "Writes a hashed credential to the global .env file and exits "
            "without starting the server."
        ),
    )
    return parser.parse_args(argv)


def set_password_cli():
    """Prompt for username and password, write hashed credential to the
    global .env file. Never echoes the password. Never accepts the
    password via a CLI flag (shell history leakage)."""
    import getpass

    from server import auth
    from server.workspace_manager import GLOBAL_DIR

    os.makedirs(GLOBAL_DIR, exist_ok=True)
    path = auth.env_path(GLOBAL_DIR)

    print(f"Setting Bullpen login credentials in {path}")
    try:
        username = input("Username: ").strip()
    except EOFError:
        print("Aborted.", file=sys.stderr)
        return 1
    if not username:
        print("Error: username cannot be blank.", file=sys.stderr)
        return 1

    try:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
    except EOFError:
        print("Aborted.", file=sys.stderr)
        return 1
    if not password:
        print("Error: password cannot be blank.", file=sys.stderr)
        return 1
    if password != confirm:
        print("Error: passwords did not match.", file=sys.stderr)
        return 1

    # Preserve any existing entries (e.g. BULLPEN_SECRET_KEY) so we don't
    # invalidate active sessions when rotating the password.
    existing = auth.parse_env_file(path)
    existing[auth.USERNAME_KEY] = username
    existing[auth.PASSWORD_HASH_KEY] = auth.generate_password_hash(password)
    auth.write_env_file(path, existing)
    print(f"Credentials written to {path} (mode 600).")
    print("Restart Bullpen to apply.")
    return 0


def require_auth_for_network_bind(host):
    """Require auth when binding beyond localhost."""
    if host in LOCALHOST_BINDS:
        return

    from server import auth
    from server.workspace_manager import GLOBAL_DIR

    auth.load_credentials(GLOBAL_DIR)
    if auth.auth_enabled():
        return

    raise RuntimeError(
        f"refusing to bind to '{host}' without authentication enabled; "
        "run `python3 bullpen.py --set-password` first"
    )


def main():
    args = parse_args()

    if args.set_password:
        sys.exit(set_password_cli())

    workspace = os.path.abspath(args.workspace)

    if not os.path.isdir(workspace):
        print(f"Error: workspace directory does not exist: {workspace}", file=sys.stderr)
        sys.exit(1)

    try:
        require_auth_for_network_bind(args.host)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Bullpen starting — workspace: {workspace}, host: {args.host}, port: {args.port}")

    from server.app import create_app, socketio

    app = create_app(workspace, no_browser=args.no_browser, host=args.host, port=args.port)

    if not args.no_browser:
        import webbrowser
        import threading
        browse_host = "localhost" if args.host == "0.0.0.0" else args.host
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{browse_host}:{args.port}")).start()

    socketio.run(app, host=args.host, port=args.port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
