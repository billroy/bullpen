#!/usr/bin/env python3
"""Bullpen — AI agent team manager."""

import argparse
import os
import sys


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
    return parser.parse_args(argv)


def main():
    args = parse_args()
    workspace = os.path.abspath(args.workspace)

    if not os.path.isdir(workspace):
        print(f"Error: workspace directory does not exist: {workspace}", file=sys.stderr)
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
