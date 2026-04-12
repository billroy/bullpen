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
        "--websocket-debug",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Enable Socket.IO / Engine.IO websocket activity logging "
            "(default: enabled for testing)"
        ),
    )
    parser.add_argument(
        "--set-password",
        nargs="?",
        action="append",
        metavar="USERNAME",
        const="",
        help=(
            "Interactively set/update login password(s). "
            "Repeat to set multiple users, e.g. "
            "`--set-password admin --set-password alice`. "
            "If passed without a value, prompts for username. "
            "Writes hashed credentials to the global .env file and exits "
            "without starting the server."
        ),
    )
    parser.add_argument(
        "--delete-user",
        action="append",
        metavar="USERNAME",
        help=(
            "Delete a user from configured login credentials. "
            "Repeat to delete multiple users. "
            "Can be combined with --set-password."
        ),
    )
    return parser.parse_args(argv)


def set_password_cli(set_usernames=None, delete_usernames=None):
    """Prompt for username/password updates, write hashed credentials to the
    global .env file. Never echoes the password. Never accepts the
    password via a CLI flag (shell history leakage)."""
    import getpass

    from server import auth
    from server.workspace_manager import GLOBAL_DIR

    os.makedirs(GLOBAL_DIR, exist_ok=True)
    path = auth.env_path(GLOBAL_DIR)

    existing = auth.parse_env_file(path)
    users = auth.parse_credentials_mapping(existing)
    set_usernames = list(set_usernames or [])
    delete_usernames = list(delete_usernames or [])

    print(f"Updating Bullpen login credentials in {path}")

    for requested_username in set_usernames:
        username = (requested_username or "").strip()
        if not username:
            try:
                username = input("Username: ").strip()
            except EOFError:
                print("Aborted.", file=sys.stderr)
                return 1
        if not username:
            print("Error: username cannot be blank.", file=sys.stderr)
            return 1

        try:
            password = getpass.getpass(f"Password for {username}: ")
            confirm = getpass.getpass(f"Confirm password for {username}: ")
        except EOFError:
            print("Aborted.", file=sys.stderr)
            return 1
        if not password:
            print("Error: password cannot be blank.", file=sys.stderr)
            return 1
        if password != confirm:
            print("Error: passwords did not match.", file=sys.stderr)
            return 1

        users[username] = auth.generate_password_hash(password)
        print(f"Updated password for user '{username}'.")

    for raw_username in delete_usernames:
        username = (raw_username or "").strip()
        if not username:
            print("Error: --delete-user requires a username.", file=sys.stderr)
            return 1
        if username in users:
            users.pop(username, None)
            print(f"Deleted user '{username}'.")
        else:
            print(f"User '{username}' not found; no change.", file=sys.stderr)

    updated = auth.apply_credentials_mapping(existing, users)
    auth.write_env_file(path, updated)
    if users:
        print(f"Credentials written to {path} (mode 600). {len(users)} user(s) configured.")
    else:
        print(f"Credentials written to {path} (mode 600). No users configured.")
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

    if args.set_password is not None or args.delete_user:
        sys.exit(set_password_cli(args.set_password or [], args.delete_user or []))

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

    app = create_app(
        workspace,
        no_browser=args.no_browser,
        host=args.host,
        port=args.port,
        websocket_debug=args.websocket_debug,
    )

    if not args.no_browser:
        import webbrowser
        import threading
        browse_host = "localhost" if args.host == "0.0.0.0" else args.host
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{browse_host}:{args.port}")).start()

    socketio.run(app, host=args.host, port=args.port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
