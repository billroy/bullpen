#!/usr/bin/env python3
"""Run the Bullpen Manager web app."""

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="bullpen-manager",
        description="Manage local and sandboxed Bullpen instances",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("BULLPEN_MANAGER_PORT", "5757")),
        help="Port to serve the manager on (default: 5757)",
    )
    parser.add_argument(
        "--home",
        default=os.environ.get("BULLPEN_MANAGER_HOME"),
        help="Manager state directory (default: ~/.bullpen/manager)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the manager in a browser",
    )
    parser.add_argument(
        "--websocket-debug",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable Socket.IO / Engine.IO logging",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print("Error: Gen 1 manager only supports localhost binds.", file=sys.stderr)
        return 1

    from server.manager import create_manager_app

    home = Path(args.home).expanduser() if args.home else None
    app, socketio = create_manager_app(home=home, websocket_debug=args.websocket_debug)
    browse_host = "localhost" if args.host in {"127.0.0.1", "::1"} else args.host
    url = f"http://{browse_host}:{args.port}"
    print(f"Bullpen Manager starting - {url}")
    if home:
        print(f"Manager home: {home}")

    if not args.no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    socketio.run(app, host=args.host, port=args.port, debug=False, allow_unsafe_werkzeug=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
