#!/usr/bin/env python3
"""Minimal MCP stdio server exposing bullpen ticket tools to agents.

Speaks JSON-RPC 2.0 over stdin/stdout (newline-delimited JSON).
Connects to the bullpen socket.io server for create/update operations
so the UI updates live. Uses direct file reads for list operations.

Usage:
    python -m server.mcp_tools --bp-dir /path/to/.bullpen --port 5000
"""

import argparse
import json
import logging
import sys
import threading

import socketio

from server import tasks as task_mod

VALID_TYPES = ("task", "bug", "feature", "chore")
VALID_PRIORITIES = ("low", "normal", "high", "urgent")

TOOLS = [
    {
        "name": "create_ticket",
        "description": "Create a new ticket in the bullpen inbox.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the ticket"},
                "description": {"type": "string", "description": "Detailed description (markdown)", "default": ""},
                "type": {"type": "string", "enum": list(VALID_TYPES), "default": "task"},
                "priority": {"type": "string", "enum": list(VALID_PRIORITIES), "default": "normal"},
                "tags": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_tickets",
        "description": "List all tickets, optionally filtered by status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status (inbox, assigned, in_progress, review, done, blocked). Omit for all.",
                },
            },
        },
    },
    {
        # Compatibility alias.
        "name": "list_tasks",
        "description": "Alias for list_tickets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status (inbox, assigned, in_progress, review, done, blocked). Omit for all.",
                },
            },
        },
    },
    {
        "name": "update_ticket",
        "description": "Update fields on an existing ticket.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Ticket ID (slug)"},
                "title": {"type": "string"},
                "body": {"type": "string", "description": "Full body text (markdown)"},
                "type": {"type": "string", "enum": list(VALID_TYPES)},
                "priority": {"type": "string", "enum": list(VALID_PRIORITIES)},
                "status": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id"],
        },
    },
]


# --- JSON-RPC helpers ---

def _read():
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def _write(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _result(msg_id, result):
    _write({"jsonrpc": "2.0", "id": msg_id, "result": result})


def _error(msg_id, code, message):
    _write({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def _tool_result(msg_id, text, is_error=False):
    _result(msg_id, {"content": [{"type": "text", "text": text}], "isError": is_error})


# --- Socket.io client for write operations ---

class BullpenClient:
    """Socket.io client that connects to the bullpen server for write ops."""

    def __init__(self, host, port):
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self.ws_id = None
        self.connected = False
        self.host = host
        self.port = port
        self._pending = {}  # msg_id -> threading.Event, result
        self._lock = threading.Lock()

        @self.sio.on("state:init")
        def on_state_init(data):
            self.ws_id = data.get("workspaceId")

        @self.sio.on("task:created")
        def on_task_created(data):
            self._resolve_pending("create", data)

        @self.sio.on("task:updated")
        def on_task_updated(data):
            self._resolve_pending("update", data)

        @self.sio.on("error")
        def on_error(data):
            self._resolve_pending_error(data.get("message", "Unknown error"))

        self._connect_best_effort()

    def _candidate_urls(self):
        hosts = [self.host]
        if self.host == "0.0.0.0":
            hosts.extend(["127.0.0.1", "localhost"])
        return [f"http://{h}:{self.port}" for h in hosts]

    def _connect_best_effort(self):
        if self.connected:
            return True
        for url in self._candidate_urls():
            try:
                self.sio.connect(url)
                self.connected = True
                return True
            except Exception:
                continue
        return False

    def _resolve_pending(self, op, data):
        with self._lock:
            entry = self._pending.pop(op, None)
        if entry:
            entry["result"] = data
            entry["event"].set()

    def _resolve_pending_error(self, message):
        with self._lock:
            # Resolve any pending operation with the error
            for key in list(self._pending.keys()):
                entry = self._pending.pop(key)
                entry["error"] = message
                entry["event"].set()
                break

    def _wait_for(self, op, timeout=10):
        event = threading.Event()
        entry = {"event": event, "result": None, "error": None}
        with self._lock:
            self._pending[op] = entry
        return entry, event

    def create_ticket(self, args):
        if not self._connect_best_effort():
            return None, "Bullpen socket connection unavailable for create_ticket"
        entry, event = self._wait_for("create")
        self.sio.emit("task:create", {
            "workspaceId": self.ws_id,
            "title": args.get("title", "Untitled"),
            "description": args.get("description", ""),
            "type": args.get("type", "task"),
            "priority": args.get("priority", "normal"),
            "tags": args.get("tags", []),
        })
        event.wait(timeout=10)
        if entry["error"]:
            return None, entry["error"]
        return entry["result"], None

    def update_ticket(self, args):
        if not self._connect_best_effort():
            return None, "Bullpen socket connection unavailable for update_ticket"
        entry, event = self._wait_for("update")
        payload = {k: v for k, v in args.items()}
        payload["workspaceId"] = self.ws_id
        self.sio.emit("task:update", payload)
        event.wait(timeout=10)
        if entry["error"]:
            return None, entry["error"]
        return entry["result"], None

    def disconnect(self):
        try:
            if self.connected:
                self.sio.disconnect()
        except Exception:
            pass


# --- Tool dispatch ---

def handle_call(bp_dir, client, msg_id, name, args):
    if name == "create_ticket":
        title = args.get("title", "").strip()
        if not title:
            return _tool_result(msg_id, "Error: title is required", is_error=True)
        task, err = client.create_ticket(args)
        if err:
            return _tool_result(msg_id, f"Error: {err}", is_error=True)
        _tool_result(msg_id, json.dumps({"id": task["id"], "title": task["title"], "status": task["status"]}))

    elif name in ("list_tickets", "list_tasks"):
        # Read-only: direct file access is fine
        tasks = task_mod.list_tasks(bp_dir)
        status_filter = args.get("status")
        if status_filter:
            tasks = [t for t in tasks if t.get("status") == status_filter]
        summary = [{"id": t["id"], "title": t["title"], "status": t.get("status"),
                     "type": t.get("type"), "priority": t.get("priority")} for t in tasks]
        _tool_result(msg_id, json.dumps(summary, indent=2))

    elif name == "update_ticket":
        ticket_id = args.get("id", "").strip()
        if not ticket_id:
            return _tool_result(msg_id, "Error: id is required", is_error=True)
        task, err = client.update_ticket(args)
        if err:
            return _tool_result(msg_id, f"Error: {err}", is_error=True)
        _tool_result(msg_id, json.dumps({"id": task["id"], "title": task["title"], "status": task.get("status")}))

    else:
        _error(msg_id, -32602, f"Unknown tool: {name}")


# --- Main loop ---

def main(bp_dir, host, port):
    client = BullpenClient(host, port)
    if not client.connected:
        logging.warning(
            "Bullpen MCP write channel unavailable at startup (%s:%s); read-only tools still active",
            host,
            port,
        )

    try:
        while True:
            msg = _read()
            if msg is None:
                break

            method = msg.get("method")
            msg_id = msg.get("id")

            if method == "initialize":
                _result(msg_id, {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "bullpen", "version": "1.0.0"},
                })

            elif method == "notifications/initialized":
                pass

            elif method == "tools/list":
                _result(msg_id, {"tools": TOOLS, "nextCursor": None})

            elif method == "tools/call":
                params = msg.get("params", {})
                handle_call(bp_dir, client, msg_id, params.get("name"), params.get("arguments", {}))

            elif msg_id is not None:
                _error(msg_id, -32601, f"Method not found: {method}")
    finally:
        client.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bp-dir", required=True, help="Path to .bullpen directory")
    parser.add_argument("--host", default="127.0.0.1", help="Bullpen server host")
    parser.add_argument("--port", type=int, default=5000, help="Bullpen server port")
    args = parser.parse_args()
    main(args.bp_dir, args.host, args.port)
