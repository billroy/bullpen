"""Exercise browser-equivalent dynamic model events against a test server."""

from __future__ import annotations

import sys
import threading

import socketio


def main():
    port = int(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else "both"
    ready = threading.Event()
    completed = {"claude": threading.Event(), "codex": threading.Event()}
    state = {}
    client = socketio.Client(
        logger=False,
        engineio_logger=False,
        reconnection=False,
        handle_sigint=False,
    )

    @client.on("state:init")
    def on_state_init(data):
        state["workspace_id"] = data.get("workspaceId")
        ready.set()

    @client.on("models:claude:listed")
    def on_claude(_data):
        completed["claude"].set()

    @client.on("models:codex:listed")
    def on_codex(_data):
        completed["codex"].set()

    client.connect(f"http://127.0.0.1:{port}")
    if not ready.wait(5):
        raise RuntimeError("server did not send state:init")
    workspace_id = state["workspace_id"]
    if mode in {"both", "claude-only"}:
        client.emit("models:claude", {"workspaceId": workspace_id, "refresh": True})
        print("MODEL_REQUEST_SENT claude", flush=True)
    if mode in {"both", "codex-only"}:
        client.emit("models:codex", {"workspaceId": workspace_id, "refresh": True})
        print("MODEL_REQUEST_SENT codex", flush=True)
    if mode in {"both", "claude-only"} and not completed["claude"].wait(30):
        raise RuntimeError("Claude model enumeration did not complete")
    if mode in {"both", "codex-only"} and not completed["codex"].wait(45):
        raise RuntimeError("Codex model enumeration did not complete")
    client.disconnect()


if __name__ == "__main__":
    main()
