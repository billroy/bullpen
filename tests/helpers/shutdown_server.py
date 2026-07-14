"""Isolated Bullpen entry point used by PTY shutdown integration tests."""

from __future__ import annotations

import os
import signal
import sys
import time
import traceback

claude_models = None
codex_models = None
bullpen = None


def _catalog_result():
    return {
        "status": "ok",
        "models": [],
        "cached": False,
        "source": "shutdown-test",
    }


def _configure_catalog_refresh():
    mode = os.environ.get("BULLPEN_SHUTDOWN_TEST_CATALOG", "immediate")

    if mode == "live":
        return
    if mode == "thread-crash":
        def crash():
            raise RuntimeError("synthetic uncaught catalog thread failure")

        claude_models.refresh_claude_models_at_startup = crash
        return
    if mode in {"cert-path-blocked", "ssl-context-blocked", "urlopen-blocked"}:
        def blocked_download(_timeout):
            ca_path = claude_models.certifi.where()
            if mode == "cert-path-blocked":
                print("CATALOG_STAGE cert-path", file=sys.stderr, flush=True)
                time.sleep(30)
                raise OSError("synthetic certificate-path stop")

            context = claude_models.ssl.create_default_context(cafile=ca_path)
            if mode == "ssl-context-blocked":
                print("CATALOG_STAGE ssl-context", file=sys.stderr, flush=True)
                time.sleep(30)
                raise OSError("synthetic SSL-context stop")

            print("CATALOG_STAGE urlopen", file=sys.stderr, flush=True)
            time.sleep(30)
            raise OSError("synthetic urlopen stop")

        claude_models._download_catalog = blocked_download
        return
    if mode == "blocked":
        def refresh():
            time.sleep(30)
            return _catalog_result()
    elif mode == "error":
        def refresh():
            return {
                **_catalog_result(),
                "status": "error",
                "error": "synthetic catalog failure",
            }
    else:
        refresh = _catalog_result

    claude_models.refresh_claude_models_at_startup = refresh


def _configure_codex_catalog():
    if os.environ.get("BULLPEN_SHUTDOWN_TEST_CODEX") != "subprocess-blocked":
        return

    def blocked_run(_codex_bin, _workspace, _timeout_seconds, *, bundled=False):
        del bundled
        print("CODEX_STAGE subprocess", file=sys.stderr, flush=True)
        import subprocess

        subprocess.run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            check=True,
        )
        raise RuntimeError("synthetic Codex subprocess stop")

    codex_models._find_codex = lambda: sys.executable
    codex_models._run_catalog = blocked_run


def main():
    global bullpen, claude_models, codex_models

    if os.environ.get("BULLPEN_SHUTDOWN_TEST_AUDIT_SIGNALS") == "1":
        original_signal = signal.signal

        def audited_signal(signum, handler):
            if signum == signal.SIGINT:
                print(
                    "SIGINT_HANDLER_SET " + repr(handler) + "\n"
                    + "".join(traceback.format_stack(limit=8)),
                    file=sys.stderr,
                    flush=True,
                )
            return original_signal(signum, handler)

        signal.signal = audited_signal

    import bullpen as bullpen_module
    try:
        from server import claude_models as claude_models_module
    except ImportError:
        claude_models_module = None
    try:
        from server import codex_models as codex_models_module
    except ImportError:
        codex_models_module = None

    bullpen = bullpen_module
    claude_models = claude_models_module
    codex_models = codex_models_module
    if claude_models is not None:
        _configure_catalog_refresh()
    if codex_models is not None:
        _configure_codex_catalog()
    if os.environ.get("BULLPEN_SHUTDOWN_TEST_SWALLOW_SIGINT") == "1":
        signal.signal(signal.SIGINT, lambda _signum, _frame: None)
    if os.environ.get("BULLPEN_SHUTDOWN_TEST_SKIP_SIGINT_RESTORE") == "1" and hasattr(
        bullpen, "restore_server_sigint_handler"
    ):
        bullpen.restore_server_sigint_handler = lambda: None
    bullpen.main()


if __name__ == "__main__":
    main()
