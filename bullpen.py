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

    print(f"Bullpen starting — workspace: {workspace}, port: {args.port}")

    # TODO: init .bullpen/, create app, start server


if __name__ == "__main__":
    main()
