#!/usr/bin/env python3
"""VGER: compare host and Microsandbox runtime details relevant to Claude TLS.

The script is intentionally self-contained and safe to run on the host or from
inside the guest. It writes diagnostics under tmp/vger by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOSTS = [
    "api.anthropic.com",
    "claude.com",
    "platform.claude.com",
    "console.anthropic.com",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect host/sandbox diagnostics for Claude auth TLS")
    parser.add_argument("--label", default="host")
    parser.add_argument("--out-dir", default=str(ROOT / "tmp" / "vger"))
    parser.add_argument("--hosts", nargs="*", default=DEFAULT_HOSTS)
    return parser.parse_args()


def run_command(command: list[str], *, timeout: int = 20, input_text: str | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as exc:
        return {
            "command": command,
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_shell(command: str, *, timeout: int = 20, input_text: str | None = None) -> dict[str, Any]:
    return run_command(["bash", "-lc", command], timeout=timeout, input_text=input_text)


def read_file(path: str, *, max_bytes: int = 200_000) -> dict[str, Any]:
    p = Path(path)
    try:
        data = p.read_bytes()
    except Exception as exc:
        return {"path": path, "exists": p.exists(), "error": f"{type(exc).__name__}: {exc}"}
    digest = hashlib.sha256(data).hexdigest()
    return {
        "path": path,
        "exists": True,
        "size": len(data),
        "sha256": digest,
        "text": data[:max_bytes].decode("utf-8", errors="replace"),
        "truncated": len(data) > max_bytes,
    }


def path_info(path: str) -> dict[str, Any]:
    p = Path(path)
    try:
        st = p.stat()
        return {
            "path": path,
            "exists": True,
            "is_dir": p.is_dir(),
            "is_file": p.is_file(),
            "mode": oct(st.st_mode & 0o7777),
            "uid": st.st_uid,
            "gid": st.st_gid,
            "size": st.st_size,
        }
    except Exception as exc:
        return {"path": path, "exists": p.exists(), "error": f"{type(exc).__name__}: {exc}"}


def command_path(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def resolve_host(host: str) -> dict[str, Any]:
    result: dict[str, Any] = {"host": host}
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        addresses = sorted({info[4][0] for info in infos})
        result["addresses"] = addresses
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def python_tls_probe(host: str) -> dict[str, Any]:
    result: dict[str, Any] = {"host": host}
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
                der = tls.getpeercert(binary_form=True) or b""
                result.update(
                    {
                        "ok": True,
                        "version": tls.version(),
                        "cipher": tls.cipher(),
                        "peer_sha256": hashlib.sha256(der).hexdigest() if der else "",
                        "subject": cert.get("subject"),
                        "issuer": cert.get("issuer"),
                        "notBefore": cert.get("notBefore"),
                        "notAfter": cert.get("notAfter"),
                    }
                )
    except Exception as exc:
        result.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return result


def collect(label: str, hosts: list[str], out_dir: Path) -> dict[str, Any]:
    artifact_dir = out_dir / label
    artifact_dir.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "label": label,
        "argv": sys.argv,
        "cwd": str(Path.cwd()),
        "python": sys.version,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "platform": platform.platform(),
        },
        "time": {
            "time": time.time(),
            "gmtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "localtime": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
            "monotonic": time.monotonic(),
            "tz": os.environ.get("TZ", ""),
        },
        "env_subset": {
            key: os.environ.get(key, "")
            for key in [
                "HOME",
                "USER",
                "LOGNAME",
                "SHELL",
                "PATH",
                "LANG",
                "LC_ALL",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
                "NODE_EXTRA_CA_CERTS",
                "BUN_OPTIONS",
                "BUN_CONFIG_VERBOSE_FETCH",
                "NODE_TLS_REJECT_UNAUTHORIZED",
                "REQUESTS_CA_BUNDLE",
                "CURL_CA_BUNDLE",
                "XDG_CONFIG_HOME",
            ]
        },
        "commands_available": {name: command_path(name) for name in ["bash", "curl", "openssl", "node", "bun", "claude", "getent", "ip", "route", "ss", "strace", "strings"]},
        "paths": [path_info(path) for path in [
            "/etc/ssl/certs/ca-certificates.crt",
            "/etc/ssl/certs",
            "/usr/local/share/ca-certificates",
            "/etc/resolv.conf",
            "/etc/nsswitch.conf",
            "/etc/hosts",
            "/etc/passwd",
            "/etc/os-release",
            "/tmp",
            "/home/bullpen",
            str(Path.home()),
        ]],
        "files": {
            path: read_file(path)
            for path in [
                "/etc/resolv.conf",
                "/etc/nsswitch.conf",
                "/etc/hosts",
                "/etc/os-release",
                "/proc/self/status",
                "/proc/self/limits",
                "/proc/mounts",
                "/proc/net/route",
                "/proc/net/if_inet6",
            ]
        },
        "dns": {host: resolve_host(host) for host in hosts},
        "python_tls": {host: python_tls_probe(host) for host in hosts},
        "commands": {},
    }

    command_specs = {
        "uname": "uname -a",
        "id": "id",
        "date": "date -u; date; date +%s",
        "ulimit": "ulimit -a",
        "openssl_version": "openssl version -a",
        "curl_version": "curl --version",
        "node_version": "node --version",
        "bun_version": "bun --version",
        "claude_version": "claude --version",
        "claude_path": "command -v claude; readlink -f \"$(command -v claude)\" 2>/dev/null || true; ls -l \"$(command -v claude)\" 2>/dev/null || true",
        "claude_package": "ls -l /usr/local/lib/node_modules/@anthropic-ai/claude-code 2>/dev/null || true; ls -l /usr/local/lib/node_modules/@anthropic-ai/claude-code/bin 2>/dev/null || true",
        "routes": "(ip route || route -n || netstat -rn) 2>&1",
        "interfaces": "(ip addr || ifconfig -a) 2>&1",
        "ca_count": "find /etc/ssl/certs -maxdepth 1 -type f 2>/dev/null | wc -l; find /etc/ssl/certs -maxdepth 1 -type l 2>/dev/null | wc -l",
    }
    for name, command in command_specs.items():
        data["commands"][name] = run_shell(command)

    for host in hosts:
        safe = host.replace(".", "_")
        data["commands"][f"getent_{safe}"] = run_shell(f"getent hosts {shlex.quote(host)} || true")
        data["commands"][f"curl_head_{safe}"] = run_shell(
            f"curl -Iv --connect-timeout 10 --max-time 20 https://{shlex.quote(host)}/",
            timeout=25,
        )
        data["commands"][f"openssl_s_client_{safe}"] = run_shell(
            "openssl s_client "
            f"-servername {shlex.quote(host)} "
            f"-connect {shlex.quote(host)}:443 "
            "-verify_return_error -showcerts </dev/null",
            timeout=25,
        )
        node_probe = (
            "const https=require('https');"
            f"https.get('https://{host}/', r => {{ console.log(JSON.stringify({{statusCode:r.statusCode, headers:r.headers}})); r.resume(); }})."
            "on('error', e => { console.error(e && (e.stack || e.message || String(e))); process.exit(1); });"
        )
        data["commands"][f"node_https_{safe}"] = run_command(["node", "-e", node_probe], timeout=25)
        bun_probe = (
            f"fetch('https://{host}/', {{method:'HEAD'}})"
            ".then(r => console.log(JSON.stringify({status:r.status, ok:r.ok, url:r.url})))"
            ".catch(e => { console.error(e && (e.stack || e.message || String(e))); process.exit(1); })"
        )
        data["commands"][f"bun_fetch_{safe}"] = run_command(["bun", "-e", bun_probe], timeout=25)

    claude_real = data["commands"]["claude_path"].get("stdout", "").splitlines()
    if len(claude_real) >= 2 and claude_real[1]:
        real_path = claude_real[1].strip()
        data["claude_binary"] = {
            "real_path": real_path,
            "file": run_shell(f"file {shlex.quote(real_path)}"),
            "ldd": run_shell(f"ldd {shlex.quote(real_path)} 2>&1 || true"),
            "strings_ca_hints": run_shell(
                f"strings {shlex.quote(real_path)} 2>/dev/null | "
                "grep -Ei 'ssl|cert|ca-certificates|boringssl|openssl|unknown certificate|api\\.anthropic|oauth' | "
                "head -300 || true",
                timeout=30,
            ),
        }

    json_path = artifact_dir / "vger.json"
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    summary_lines = [
        f"label: {label}",
        f"cwd: {data['cwd']}",
        f"platform: {data['platform']['platform']}",
        f"time_utc: {data['time']['gmtime']}",
        "commands:",
    ]
    for name, path in data["commands_available"].items():
        summary_lines.append(f"  {name}: {path or 'missing'}")
    summary_lines.append("dns:")
    for host, result in data["dns"].items():
        summary_lines.append(f"  {host}: {result.get('addresses') or result.get('error')}")
    summary_lines.append("python_tls:")
    for host, result in data["python_tls"].items():
        if result.get("ok"):
            summary_lines.append(f"  {host}: ok {result.get('version')} {result.get('peer_sha256')}")
        else:
            summary_lines.append(f"  {host}: {result.get('error')}")
    (artifact_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return data


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()
    try:
        out_dir.relative_to(ROOT.resolve())
    except ValueError:
        print(f"error: refusing to write outside {ROOT}: {out_dir}", file=sys.stderr)
        return 1
    data = collect(args.label, args.hosts, out_dir)
    print(out_dir / args.label / "summary.txt")
    print(out_dir / args.label / "vger.json")
    return 0 if data else 1


if __name__ == "__main__":
    raise SystemExit(main())
