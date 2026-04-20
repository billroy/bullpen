"""Runtime controller for Service workers."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from server.persistence import read_json
from server.worker_types import normalize_layout


SERVICE_LOG_DEFAULT_MAX = 5 * 1024 * 1024
SERVICE_SECRET_ENV_MARKERS = (
    "TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL", "PASSPHRASE",
)

_controllers = {}
_controllers_lock = threading.Lock()


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event_id():
    return datetime.now(timezone.utc).strftime("manual-%Y%m%dT%H%M%S%fZ")


def _emit(socketio, event, payload, ws_id):
    if not socketio:
        return
    if isinstance(payload, dict):
        payload["workspaceId"] = ws_id
    socketio.emit(event, payload, to=ws_id)


def _is_secret_env_name(name):
    upper = str(name or "").upper()
    return any(marker in upper for marker in SERVICE_SECRET_ENV_MARKERS)


def _minimal_env(configured_env):
    if sys.platform == "win32":
        allowed = {"PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"}
        env = {
            key: value for key, value in os.environ.items()
            if key.upper() in allowed and not _is_secret_env_name(key)
        }
    else:
        env = {
            key: value for key, value in os.environ.items()
            if (key in {"PATH", "HOME", "LANG", "TZ"} or key.startswith("LC_"))
            and not _is_secret_env_name(key)
        }

    env.pop("BULLPEN_MCP_TOKEN", None)
    for item in configured_env or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        if key == "BULLPEN_MCP_TOKEN" or key.startswith("BULLPEN_"):
            raise ValueError(f"{key} cannot be configured for Service workers.")
        env[key] = str(item.get("value") or "")
    return env


def _resolve_cwd(workspace, configured_cwd):
    configured_cwd = str(configured_cwd or "").strip()
    cwd = os.path.join(workspace, configured_cwd) if configured_cwd and not os.path.isabs(configured_cwd) else (configured_cwd or workspace)
    real = os.path.realpath(cwd)
    root = os.path.realpath(workspace)
    if real != root and not real.startswith(root + os.sep):
        raise ValueError("Service worker cwd escapes the workspace.")
    if not os.path.isdir(real):
        raise ValueError("Service worker cwd does not exist.")
    return real


def _popen_kwargs():
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _terminate_tree(proc, *, graceful=True):
    if not proc or proc.poll() is not None:
        return
    if sys.platform == "win32":
        if graceful:
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
                return
            except Exception:
                pass
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        return
    try:
        pgid = os.getpgid(proc.pid)
        sig = signal.SIGTERM if graceful else signal.SIGKILL
        if pgid != os.getpgrp():
            os.killpg(pgid, sig)
            return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        if graceful:
            proc.terminate()
        else:
            proc.kill()
    except OSError:
        pass


def _command_argv(command):
    if sys.platform == "win32":
        return ["cmd.exe", "/c", command]
    return ["/bin/sh", "-c", command]


def _load_service_slot(bp_dir, slot_index):
    config = read_json(os.path.join(bp_dir, "config.json"))
    layout = normalize_layout(read_json(os.path.join(bp_dir, "layout.json")), config=config)
    slots = layout.get("slots", [])
    if slot_index is None or slot_index < 0 or slot_index >= len(slots) or not slots[slot_index]:
        raise ValueError("Service worker slot not found.")
    worker = slots[slot_index]
    if worker.get("type") != "service":
        raise ValueError("Selected worker is not a Service worker.")
    return worker


class ServiceWorkerController:
    def __init__(self, bp_dir, ws_id, slot_index, socketio=None):
        self.bp_dir = bp_dir
        self.workspace = os.path.dirname(bp_dir)
        self.ws_id = ws_id
        self.slot_index = int(slot_index)
        self.socketio = socketio
        self._lock = threading.RLock()
        self._log_lock = threading.Lock()
        self._op_thread = None
        self._reader_thread = None
        self._proc = None
        self._pre_start_proc = None
        self._cancel = threading.Event()
        self._state = "stopped"
        self._health = None
        self._pid = None
        self._started_at = None
        self._exit_code = None
        self._active_config_hash = None
        self._config_hash = None
        self._last_error = None

    @property
    def log_dir(self):
        return os.path.join(self.bp_dir, "logs", "services", f"slot-{self.slot_index}")

    @property
    def log_path(self):
        return os.path.join(self.log_dir, "service.log")

    @property
    def rotated_log_path(self):
        return os.path.join(self.log_dir, "service.log.1")

    def state_snapshot(self):
        with self._lock:
            return {
                "slot": self.slot_index,
                "state": self._state,
                "health": self._health,
                "pid": self._pid,
                "started_at": self._started_at,
                "exit_code": self._exit_code,
                "config_hash": self._config_hash,
                "active_config_hash": self._active_config_hash,
                "last_error": self._last_error,
            }

    def emit_state(self):
        _emit(self.socketio, "service:state", self.state_snapshot(), self.ws_id)

    def emit_log(self, lines, *, catchup=False, reset=False):
        if isinstance(lines, str):
            lines = [lines]
        payload = {
            "slot": self.slot_index,
            "lines": [line.rstrip("\n") for line in lines],
            "catchup": bool(catchup),
            "reset": bool(reset),
        }
        _emit(self.socketio, "service:log", payload, self.ws_id)

    def start(self):
        thread = threading.Thread(target=self._start_sequence, daemon=True)
        with self._lock:
            if self._state in ("starting", "running", "stopping"):
                self.emit_state()
                return False
            self._cancel.clear()
            self._state = "starting"
            self._pid = None
            self._started_at = None
            self._last_error = None
            self._op_thread = thread
            self.emit_state()
        thread.start()
        return True

    def restart(self):
        thread = threading.Thread(target=self._restart_sequence, daemon=True)
        with self._lock:
            if self._state in ("starting", "stopping"):
                self.emit_state()
                return False
            self._cancel.clear()
            self._state = "stopping" if self._state == "running" else "starting"
            self._last_error = None
            self._op_thread = thread
            self.emit_state()
        thread.start()
        return True

    def stop(self):
        self._cancel.set()
        with self._lock:
            if self._state == "stopped":
                self.emit_state()
                return False
            self._state = "stopping"
            self._last_error = None
            self.emit_state()
            pre_start_proc = self._pre_start_proc
            proc = self._proc
            timeout = self._current_stop_timeout()
        if pre_start_proc and pre_start_proc.poll() is None:
            _terminate_tree(pre_start_proc, graceful=True)
        if proc and proc.poll() is None:
            _terminate_tree(proc, graceful=True)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _terminate_tree(proc, graceful=False)
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        with self._lock:
            if not self._proc or self._proc.poll() is not None:
                self._state = "stopped"
                self._pid = None
                self._started_at = None
                self._exit_code = self._proc.returncode if self._proc else self._exit_code
                self._proc = None
            self._pre_start_proc = None
        self._write_log("[bullpen] service stopped\n", emit=True)
        self.emit_state()
        return True

    def tail(self, max_bytes=65536):
        try:
            max_bytes = max(1, min(int(max_bytes or 65536), 1024 * 1024))
        except (TypeError, ValueError):
            max_bytes = 65536
        chunks = []
        for path in (self.rotated_log_path, self.log_path):
            if os.path.exists(path):
                with open(path, "rb") as handle:
                    chunks.append(handle.read())
        data = b"".join(chunks)[-max_bytes:]
        text = data.decode("utf-8", errors="replace")
        self.emit_state()
        self.emit_log(text.splitlines(), catchup=True, reset=True)

    def _current_stop_timeout(self):
        try:
            worker = _load_service_slot(self.bp_dir, self.slot_index)
            return max(0, int(worker.get("stop_timeout_seconds", 5)))
        except Exception:
            return 5

    def _set_state(self, state, **updates):
        with self._lock:
            self._state = state
            for key, value in updates.items():
                setattr(self, f"_{key}", value)
        self.emit_state()

    def _start_sequence(self):
        order_id = _event_id()
        try:
            worker = _load_service_slot(self.bp_dir, self.slot_index)
            command = str(worker.get("command") or "").strip()
            if not command:
                raise ValueError("Service workers require a command.")
            self._config_hash = self._service_config_hash(worker)
            self._active_config_hash = self._config_hash
            self._exit_code = None
            self._last_error = None
            self._set_state("starting", pid=None, started_at=None)
            self._rotate_log(force=True)
            self._write_log(f"[bullpen] starting service order {order_id}\n", emit=True)

            deadline = time.monotonic() + max(1, int(worker.get("startup_timeout_seconds", 60)))
            cwd = _resolve_cwd(self.workspace, worker.get("cwd"))
            env = _minimal_env(worker.get("env"))
            env.update({
                "BULLPEN_WORKSPACE": self.workspace,
                "BULLPEN_SERVICE_SLOT": str(self.slot_index),
                "BULLPEN_SERVICE_NAME": str(worker.get("name") or ""),
                "BULLPEN_SERVICE_ORDER_ID": order_id,
                "BULLPEN_SERVICE_COMMIT": "",
                "BULLPEN_TICKET_ID": "",
                "BULLPEN_TICKET_TITLE": "",
                "BULLPEN_TICKET_STATUS": "",
                "BULLPEN_TICKET_PRIORITY": "",
                "BULLPEN_TICKET_TAGS": "",
            })

            pre_start = str(worker.get("pre_start") or "").strip()
            if pre_start:
                self._run_pre_start(pre_start, cwd, env, deadline)

            if self._cancel.is_set():
                self._set_state("stopped", pid=None, started_at=None)
                return

            proc = subprocess.Popen(
                _command_argv(command),
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                **_popen_kwargs(),
            )
            with self._lock:
                self._proc = proc
                self._pid = proc.pid
                self._started_at = _now_iso()
            self._write_log(f"[bullpen] spawned pid {proc.pid}\n", emit=True)
            self._reader_thread = threading.Thread(target=self._drain_output, args=(proc,), daemon=True)
            self._reader_thread.start()

            grace = max(0, int(worker.get("startup_grace_seconds", 2)))
            while time.monotonic() < deadline and grace > 0:
                if self._cancel.is_set() or proc.poll() is not None:
                    break
                step = min(0.1, grace)
                time.sleep(step)
                grace -= step
            if self._cancel.is_set():
                self.stop()
                return
            if proc.poll() is not None:
                raise RuntimeError(f"Service exited during startup with code {proc.returncode}.")
            if time.monotonic() >= deadline:
                raise TimeoutError("Service startup timed out.")
            self._set_state("running")
            self._write_log("[bullpen] service running\n", emit=True)
            threading.Thread(target=self._monitor, args=(proc,), daemon=True).start()
        except Exception as exc:
            self._last_error = str(exc)
            self._write_log(f"[bullpen] service start failed: {exc}\n", emit=True)
            self._cleanup_failed_start()
            self._set_state("crashed", pid=None, started_at=None)

    def _restart_sequence(self):
        self.stop()
        self._cancel.clear()
        self._start_sequence()

    def _run_pre_start(self, command, cwd, env, deadline):
        self._write_log("[bullpen] running pre-start\n", emit=True)
        proc = subprocess.Popen(
            _command_argv(command),
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            **_popen_kwargs(),
        )
        with self._lock:
            self._pre_start_proc = proc
        reader = threading.Thread(target=self._drain_output, args=(proc,), daemon=True)
        reader.start()
        while proc.poll() is None:
            if self._cancel.is_set():
                _terminate_tree(proc, graceful=True)
                break
            if time.monotonic() >= deadline:
                _terminate_tree(proc, graceful=True)
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    _terminate_tree(proc, graceful=False)
                raise TimeoutError("Pre-start timed out.")
            time.sleep(0.05)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _terminate_tree(proc, graceful=False)
            proc.wait()
        with self._lock:
            self._pre_start_proc = None
        if self._cancel.is_set():
            return
        if proc.returncode != 0:
            raise RuntimeError(f"Pre-start exited with code {proc.returncode}.")
        self._write_log("[bullpen] pre-start complete\n", emit=True)

    def _drain_output(self, proc):
        try:
            for line in proc.stdout:
                self._write_log(line, emit=True)
        except (ValueError, OSError):
            pass

    def _monitor(self, proc):
        proc.wait()
        with self._lock:
            if self._proc is not proc:
                return
            self._exit_code = proc.returncode
            was_stopping = self._state == "stopping" or self._cancel.is_set()
            self._proc = None
            self._pid = None
            self._started_at = None
            self._state = "stopped" if was_stopping else "crashed"
        if was_stopping:
            self._write_log(f"[bullpen] service exited with code {proc.returncode}\n", emit=True)
        else:
            self._write_log(f"[bullpen] service crashed with code {proc.returncode}\n", emit=True)
        self.emit_state()

    def _cleanup_failed_start(self):
        with self._lock:
            proc = self._proc
            pre = self._pre_start_proc
            self._proc = None
            self._pre_start_proc = None
            self._pid = None
            self._started_at = None
        for candidate in (pre, proc):
            if candidate and candidate.poll() is None:
                _terminate_tree(candidate, graceful=True)
                try:
                    candidate.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    _terminate_tree(candidate, graceful=False)

    def _rotate_log(self, *, force=False, incoming_len=0):
        os.makedirs(self.log_dir, exist_ok=True)
        with self._log_lock:
            should_rotate = False
            if os.path.exists(self.log_path):
                current_size = os.path.getsize(self.log_path)
                should_rotate = (force and current_size > 0) or current_size + incoming_len > self._log_max_bytes()
            if not should_rotate:
                return
            try:
                if os.path.exists(self.rotated_log_path):
                    os.remove(self.rotated_log_path)
                os.replace(self.log_path, self.rotated_log_path)
            except OSError:
                pass

    def _write_log(self, text, *, emit=False):
        if text is None:
            return
        if not text.endswith("\n"):
            text += "\n"
        data_len = len(text.encode("utf-8", errors="replace"))
        self._rotate_log(incoming_len=data_len)
        os.makedirs(self.log_dir, exist_ok=True)
        with self._log_lock:
            with open(self.log_path, "a", encoding="utf-8", errors="replace") as handle:
                handle.write(text)
        if emit:
            self.emit_log(text.splitlines())

    def _log_max_bytes(self):
        try:
            worker = _load_service_slot(self.bp_dir, self.slot_index)
            return max(1024, int(worker.get("log_max_bytes", SERVICE_LOG_DEFAULT_MAX)))
        except Exception:
            return SERVICE_LOG_DEFAULT_MAX

    def _service_config_hash(self, worker):
        # Phase 2 needs a stable comparable token; a full canonical helper can
        # grow here as ticket orders and health checks land.
        import hashlib
        import json
        fields = {
            key: worker.get(key)
            for key in (
                "command", "cwd", "env", "pre_start", "ticket_action",
                "disposition", "max_retries", "startup_grace_seconds",
                "startup_timeout_seconds", "health_type", "health_url",
                "health_command", "health_interval_seconds",
                "health_timeout_seconds", "health_failure_threshold",
                "on_crash", "stop_timeout_seconds", "log_max_bytes",
            )
        }
        payload = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_controller(bp_dir, ws_id, slot, socketio=None):
    key = (ws_id, int(slot))
    with _controllers_lock:
        controller = _controllers.get(key)
        if controller is None:
            controller = ServiceWorkerController(bp_dir, ws_id, int(slot), socketio=socketio)
            _controllers[key] = controller
        elif socketio is not None:
            controller.socketio = socketio
        return controller


def start_service(bp_dir, ws_id, slot, socketio=None):
    return get_controller(bp_dir, ws_id, slot, socketio).start()


def stop_service(bp_dir, ws_id, slot, socketio=None):
    return get_controller(bp_dir, ws_id, slot, socketio).stop()


def restart_service(bp_dir, ws_id, slot, socketio=None):
    return get_controller(bp_dir, ws_id, slot, socketio).restart()


def tail_service(bp_dir, ws_id, slot, socketio=None, max_bytes=65536):
    return get_controller(bp_dir, ws_id, slot, socketio).tail(max_bytes=max_bytes)


def stop_workspace_services(ws_id, *, wait=True):
    with _controllers_lock:
        controllers = [controller for (key_ws_id, _), controller in _controllers.items() if key_ws_id == ws_id]
    _stop_controllers(controllers, wait=wait)


def stop_all_services(*, wait=True):
    with _controllers_lock:
        controllers = list(_controllers.values())
    _stop_controllers(controllers, wait=wait)


def _stop_controllers(controllers, *, wait=True):
    threads = []
    for controller in controllers:
        thread = threading.Thread(target=controller.stop, daemon=True)
        thread.start()
        threads.append(thread)
    if wait:
        for thread in threads:
            thread.join(timeout=10)
