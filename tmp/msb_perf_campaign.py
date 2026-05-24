#!/usr/bin/env python3
"""Boundary probes for Bullpen-in-Microsandbox page-load stalls.

This is intentionally a throwaway investigation harness. It does not modify
Bullpen source or deployment code.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import socket
import statistics
import textwrap
import time
from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_PATHS = [
    "/health",
    "/style.css",
    "/utils.js",
    "/gridGeometry.js",
    "/audio.js",
    "/event-sounds.js",
    "/commands.js",
    "/components/TopToolbar.js",
    "/components/LeftPane.js",
    "/components/TaskCard.js",
    "/components/WorkerCard.js",
    "/components/KanbanTab.js",
    "/components/BullpenTab.js",
    "/components/FilesTab.js",
    "/components/StatsTab.js",
    "/components/TaskCreateModal.js",
    "/components/TaskDetailPanel.js",
    "/components/WorkerConfigModal.js",
    "/components/WorkerTransferModal.js",
    "/components/ColumnManagerModal.js",
    "/components/WorkerFocusView.js",
    "/components/CommitsTab.js",
    "/components/LiveAgentChatTab.js",
    "/components/TerminalTab.js",
    "/components/ToastContainer.js",
    "/app.js",
]


@dataclass
class FetchTiming:
    label: str
    index: int
    path: str
    start_epoch: float
    end_epoch: float
    status: int
    connect_ms: float
    send_ms: float
    ttfb_ms: float
    total_ms: float
    bytes_read: int
    error: str = ""


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[idx]


def fetch_once(host: str, port: int, path: str, *, label: str, index: int, timeout: float, connection: str) -> FetchTiming:
    start_epoch = time.time()
    start = time.perf_counter()
    connect_done = start
    send_done = start
    ttfb = start
    bytes_read = 0
    status = 0
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        connect_done = time.perf_counter()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "User-Agent: msb-perf-campaign\r\n"
            "Accept: */*\r\n"
            f"X-Msb-Probe-Index: {index}\r\n"
            f"X-Msb-Probe-Start-Epoch: {start_epoch:.9f}\r\n"
            f"Connection: {connection}\r\n"
            "\r\n"
        ).encode("ascii")
        sock.sendall(request)
        send_done = time.perf_counter()
        first = sock.recv(1)
        ttfb = time.perf_counter()
        if not first:
            raise RuntimeError("empty response")
        chunks = [first]
        raw = first
        while b"\r\n\r\n" not in raw:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            raw += chunk
        header_bytes, _sep, body = raw.partition(b"\r\n\r\n")
        content_length = None
        for line in header_bytes.split(b"\r\n")[1:]:
            name, colon, value = line.partition(b":")
            if colon and name.lower() == b"content-length":
                try:
                    content_length = int(value.strip())
                except ValueError:
                    content_length = None
        if content_length is None:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        else:
            remaining = content_length - len(body)
            while remaining > 0:
                chunk = sock.recv(min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        raw = b"".join(chunks)
        bytes_read = len(raw)
        first_line = raw.split(b"\r\n", 1)[0].decode("iso-8859-1", errors="replace")
        parts = first_line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            status = int(parts[1])
        sock.close()
        error = ""
    except Exception as exc:
        try:
            sock.close()
        except Exception:
            pass
        error = str(exc) or exc.__class__.__name__
    end = time.perf_counter()
    end_epoch = time.time()
    return FetchTiming(
        label=label,
        index=index,
        path=path,
        start_epoch=start_epoch,
        end_epoch=end_epoch,
        status=status,
        connect_ms=(connect_done - start) * 1000.0,
        send_ms=(send_done - connect_done) * 1000.0,
        ttfb_ms=(ttfb - send_done) * 1000.0,
        total_ms=(end - start) * 1000.0,
        bytes_read=bytes_read,
        error=error,
    )


async def run_batch(host: str, port: int, paths: list[str], *, label: str, concurrency: int, timeout: float, connection: str) -> dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)

    async def one(index: int, path: str) -> FetchTiming:
        async with sem:
            return await asyncio.to_thread(
                fetch_once,
                host,
                port,
                path,
                label=label,
                index=index,
                timeout=timeout,
                connection=connection,
            )

    wall_start = time.perf_counter()
    timings = await asyncio.gather(*(one(i, path) for i, path in enumerate(paths)))
    wall_ms = (time.perf_counter() - wall_start) * 1000.0
    return summarize(label, wall_ms, timings)


def summarize(label: str, wall_ms: float, timings: list[FetchTiming]) -> dict[str, Any]:
    totals = [item.total_ms for item in timings]
    ttfbs = [item.ttfb_ms for item in timings if not item.error]
    errors = [asdict(item) for item in timings if item.error]
    slowest = sorted(timings, key=lambda item: item.total_ms, reverse=True)[:8]
    return {
        "label": label,
        "count": len(timings),
        "wall_ms": wall_ms,
        "total_median_ms": statistics.median(totals) if totals else 0.0,
        "total_p95_ms": percentile(totals, 0.95),
        "ttfb_median_ms": statistics.median(ttfbs) if ttfbs else 0.0,
        "ttfb_p95_ms": percentile(ttfbs, 0.95),
        "statuses": {str(code): sum(1 for item in timings if item.status == code) for code in sorted({item.status for item in timings})},
        "errors": errors[:5],
        "slowest": [asdict(item) for item in slowest],
    }


GUEST_CLIENT = r"""
import asyncio, json, socket, statistics, time
from dataclasses import asdict, dataclass

paths = __PATHS__
host = "__HOST__"
port = __PORT__
label = "__LABEL__"
concurrency = __CONCURRENCY__
timeout = __TIMEOUT__
connection = "__CONNECTION__"

@dataclass
class FetchTiming:
    label: str
    index: int
    path: str
    start_epoch: float
    end_epoch: float
    status: int
    connect_ms: float
    send_ms: float
    ttfb_ms: float
    total_ms: float
    bytes_read: int
    error: str = ""

def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[idx]

def fetch_once(index, path):
    start_epoch = time.time()
    start = time.perf_counter()
    connect_done = send_done = ttfb = start
    bytes_read = 0
    status = 0
    error = ""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        connect_done = time.perf_counter()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "User-Agent: msb-perf-campaign\r\n"
            "Accept: */*\r\n"
            f"X-Msb-Probe-Index: {index}\r\n"
            f"X-Msb-Probe-Start-Epoch: {start_epoch:.9f}\r\n"
            f"Connection: {connection}\r\n"
            "\r\n"
        ).encode("ascii")
        sock.sendall(request)
        send_done = time.perf_counter()
        first = sock.recv(1)
        ttfb = time.perf_counter()
        if not first:
            raise RuntimeError("empty response")
        chunks = [first]
        raw = first
        while b"\r\n\r\n" not in raw:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            raw += chunk
        header_bytes, _sep, body = raw.partition(b"\r\n\r\n")
        content_length = None
        for line in header_bytes.split(b"\r\n")[1:]:
            name, colon, value = line.partition(b":")
            if colon and name.lower() == b"content-length":
                try:
                    content_length = int(value.strip())
                except ValueError:
                    content_length = None
        if content_length is None:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        else:
            remaining = content_length - len(body)
            while remaining > 0:
                chunk = sock.recv(min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        raw = b"".join(chunks)
        bytes_read = len(raw)
        first_line = raw.split(b"\r\n", 1)[0].decode("iso-8859-1", errors="replace")
        parts = first_line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            status = int(parts[1])
    except Exception as exc:
        error = str(exc) or exc.__class__.__name__
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
    end = time.perf_counter()
    end_epoch = time.time()
    return FetchTiming(label, index, path, start_epoch, end_epoch, status, (connect_done-start)*1000, (send_done-connect_done)*1000, (ttfb-send_done)*1000, (end-start)*1000, bytes_read, error)

async def main():
    sem = asyncio.Semaphore(concurrency)
    async def one(index, path):
        async with sem:
            return await asyncio.to_thread(fetch_once, index, path)
    wall_start = time.perf_counter()
    timings = await asyncio.gather(*(one(i, p) for i, p in enumerate(paths)))
    wall_ms = (time.perf_counter() - wall_start) * 1000.0
    totals = [x.total_ms for x in timings]
    ttfbs = [x.ttfb_ms for x in timings if not x.error]
    result = {
        "label": label,
        "count": len(timings),
        "wall_ms": wall_ms,
        "total_median_ms": statistics.median(totals) if totals else 0.0,
        "total_p95_ms": percentile(totals, 0.95),
        "ttfb_median_ms": statistics.median(ttfbs) if ttfbs else 0.0,
        "ttfb_p95_ms": percentile(ttfbs, 0.95),
        "statuses": {str(code): sum(1 for item in timings if item.status == code) for code in sorted({item.status for item in timings})},
        "errors": [asdict(item) for item in timings if item.error][:5],
        "slowest": [asdict(item) for item in sorted(timings, key=lambda item: item.total_ms, reverse=True)[:8]],
    }
    print(json.dumps(result, sort_keys=True))

asyncio.run(main())
"""


DIAG_SERVER = r"""
import argparse, json, socket, threading, time

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="0.0.0.0")
parser.add_argument("--port", type=int, default=3000)
parser.add_argument("--log", default="/tmp/msb_diag_http.log")
parser.add_argument("--body-bytes", type=int, default=4096)
parser.add_argument("--connection", choices=["close", "keep-alive"], default="close")
args = parser.parse_args()

body = (b"x" * args.body_bytes)
lock = threading.Lock()

def log(row):
    with lock:
        with open(args.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")

def handle(conn, addr):
    accepted = time.time()
    first_line = ""
    headers_seen = {}
    try:
        conn.settimeout(10)
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 65536:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        got_request = time.time()
        first_line = data.split(b"\r\n", 1)[0].decode("iso-8859-1", errors="replace")
        header_blob = data.split(b"\r\n\r\n", 1)[0]
        for raw_line in header_blob.split(b"\r\n")[1:]:
            name, colon, value = raw_line.partition(b":")
            if colon:
                key = name.decode("iso-8859-1", errors="replace").lower()
                if key.startswith("x-msb-probe-"):
                    headers_seen[key] = value.strip().decode("iso-8859-1", errors="replace")
        headers = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + f"Connection: {args.connection}\r\n".encode("ascii")
            + b"\r\n"
        )
        conn.sendall(headers + body)
        sent = time.time()
        log({"addr": addr[0], "port": addr[1], "accepted": accepted, "got_request": got_request, "sent": sent, "first_line": first_line, "headers": headers_seen})
    except Exception as exc:
        log({"addr": addr[0], "port": addr[1], "accepted": accepted, "error": str(exc) or exc.__class__.__name__, "first_line": first_line, "headers": headers_seen})
    finally:
        try:
            conn.close()
        except Exception:
            pass

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((args.host, args.port))
sock.listen(256)
print(json.dumps({"event": "listening", "host": args.host, "port": args.port, "connection": args.connection, "body_bytes": len(body)}), flush=True)
while True:
    conn, addr = sock.accept()
    threading.Thread(target=handle, args=(conn, addr), daemon=True).start()
"""


async def maybe(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def connect_sandbox(name: str) -> Any:
    import microsandbox

    handle = await maybe(microsandbox.Sandbox.get(name))
    return await maybe(handle.connect())


async def guest_exec(sandbox: Any, command: str) -> str:
    result = await maybe(sandbox.exec("bash", ["-lc", command]))
    stdout = getattr(result, "stdout_text", "") or getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr_text", "") or getattr(result, "stderr", "") or ""
    if stderr:
        return stdout + "\nSTDERR:\n" + stderr
    return stdout


async def guest_batch(sandbox: Any, *, host: str, port: int, paths: list[str], label: str, concurrency: int, timeout: float, connection: str) -> dict[str, Any]:
    code = GUEST_CLIENT
    code = code.replace("__PATHS__", json.dumps(paths))
    code = code.replace("__HOST__", host)
    code = code.replace("__PORT__", str(port))
    code = code.replace("__LABEL__", label)
    code = code.replace("__CONCURRENCY__", str(concurrency))
    code = code.replace("__TIMEOUT__", repr(timeout))
    code = code.replace("__CONNECTION__", connection)
    output = await guest_exec(sandbox, "python3 - <<'PY'\n" + code + "\nPY")
    return json.loads(output.strip().splitlines()[-1])


async def start_diag_server(sandbox: Any, *, port: int, connection: str, body_bytes: int) -> None:
    await guest_exec(
        sandbox,
        "python3 - <<'PY'\n"
        "import os, signal\n"
        "me = os.getpid()\n"
        "for name in os.listdir('/proc'):\n"
        "    if not name.isdigit():\n"
        "        continue\n"
        "    pid = int(name)\n"
        "    if pid == me:\n"
        "        continue\n"
        "    try:\n"
        "        cmdline = open(f'/proc/{pid}/cmdline', 'rb').read().decode('utf-8', 'ignore')\n"
        "    except Exception:\n"
        "        continue\n"
        "    if '/tmp/msb_diag_http.py' in cmdline:\n"
        "        try:\n"
        "            os.kill(pid, signal.SIGKILL)\n"
        "        except ProcessLookupError:\n"
        "            pass\n"
        "PY\n"
        ": > /tmp/msb_diag_http.log\n"
        ": > /tmp/msb_diag_http.out\n"
        ": > /tmp/msb_diag_http.err\n"
    )
    command = (
        "cat > /tmp/msb_diag_http.py <<'PY'\n"
        + DIAG_SERVER
        + "\nPY\n"
        + f"nohup python3 /tmp/msb_diag_http.py --port {port} --connection {connection} --body-bytes {body_bytes} "
        + ">/tmp/msb_diag_http.out 2>/tmp/msb_diag_http.err &\n"
        + "sleep 0.2\n"
        + "cat /tmp/msb_diag_http.out\n"
        + "cat /tmp/msb_diag_http.err >&2\n"
    )
    output = await guest_exec(sandbox, command)
    if "listening" not in output:
        raise RuntimeError(f"diagnostic server did not start: {output}")


async def main_async() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox", default="bullpen-pr-workflow-test")
    parser.add_argument("--bullpen-port", type=int, default=8080)
    parser.add_argument("--internal-port", type=int, default=18080)
    parser.add_argument("--diag-port", type=int, default=3000)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--connection", choices=["close", "keep-alive"], default="keep-alive")
    parser.add_argument("--paths", choices=["health", "static"], default="static")
    parser.add_argument("--skip-diag-server", action="store_true")
    args = parser.parse_args()

    paths = ["/health"] * 24 if args.paths == "health" else DEFAULT_PATHS
    sandbox = await connect_sandbox(args.sandbox)

    print("## subject", flush=True)
    config_out = await guest_exec(
        sandbox,
        "echo processes; ps -ef | grep -E 'bullpen.py|bullpen-proxy|nginx|python' | grep -v grep || true; "
        "echo listeners; ss -ltnp || true",
    )
    print(config_out.strip(), flush=True)

    experiments: list[dict[str, Any]] = []
    print("## guest: front port", flush=True)
    experiments.append(await guest_batch(sandbox, host="127.0.0.1", port=args.bullpen_port, paths=paths, label="guest->front", concurrency=args.concurrency, timeout=args.timeout, connection=args.connection))
    print(json.dumps(experiments[-1], indent=2, sort_keys=True), flush=True)

    print("## guest: internal port", flush=True)
    experiments.append(await guest_batch(sandbox, host="127.0.0.1", port=args.internal_port, paths=paths, label="guest->internal", concurrency=args.concurrency, timeout=args.timeout, connection=args.connection))
    print(json.dumps(experiments[-1], indent=2, sort_keys=True), flush=True)

    print("## host: exposed front port", flush=True)
    experiments.append(await run_batch("127.0.0.1", args.bullpen_port, paths, label="host->front", concurrency=args.concurrency, timeout=args.timeout, connection=args.connection))
    print(json.dumps(experiments[-1], indent=2, sort_keys=True), flush=True)

    if not args.skip_diag_server:
        print("## starting guest diagnostic server on exposed app port", flush=True)
        await start_diag_server(sandbox, port=args.diag_port, connection="close", body_bytes=4096)
        diag_paths = [f"/diag-{i}.txt" for i in range(24)]
        print("## guest: diagnostic server", flush=True)
        experiments.append(await guest_batch(sandbox, host="127.0.0.1", port=args.diag_port, paths=diag_paths, label="guest->diag", concurrency=args.concurrency, timeout=args.timeout, connection=args.connection))
        print(json.dumps(experiments[-1], indent=2, sort_keys=True), flush=True)
        print("## host: exposed diagnostic server", flush=True)
        experiments.append(await run_batch("127.0.0.1", args.diag_port, diag_paths, label="host->diag", concurrency=args.concurrency, timeout=args.timeout, connection=args.connection))
        print(json.dumps(experiments[-1], indent=2, sort_keys=True), flush=True)

    print("## compact summary", flush=True)
    print(json.dumps(experiments, indent=2, sort_keys=True), flush=True)
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
