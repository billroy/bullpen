"""Time-based scheduler for worker activation."""

import os
import threading
import time
from datetime import datetime

from server.locks import write_lock
from server.persistence import read_json
from server import workers as worker_mod


class Scheduler:
    """Background thread that checks time-based activation triggers."""

    def __init__(self, bp_dir, socketio, interval=60):
        self.bp_dir = bp_dir
        self.socketio = socketio
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Scheduler tick error: %s", e)
            self._stop_event.wait(self.interval)

    def _tick(self):
        """Check all workers for time-based triggers."""
        layout_path = os.path.join(self.bp_dir, "layout.json")
        if not os.path.exists(layout_path):
            return

        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_ts = time.time()

        with write_lock:
            layout = read_json(layout_path)

            for slot_index, worker in enumerate(layout.get("slots", [])):
                if worker is None:
                    continue
                if worker.get("state") != "idle":
                    continue
                if not worker.get("task_queue"):
                    continue

                activation = worker.get("activation")

                if activation == "at_time":
                    trigger_time = worker.get("trigger_time")
                    if trigger_time and trigger_time == current_time:
                        # Fire the worker
                        worker_mod.start_worker(self.bp_dir, slot_index, self.socketio)
                        # If not recurring, reset to manual
                        if not worker.get("trigger_every_day"):
                            worker["activation"] = "manual"
                            from server.persistence import write_json
                            write_json(layout_path, layout)

                elif activation == "on_interval":
                    interval_min = worker.get("trigger_interval_minutes")
                    last_trigger = worker.get("last_trigger_time") or 0
                    if interval_min and (current_ts - last_trigger) >= interval_min * 60:
                        worker["last_trigger_time"] = current_ts
                        from server.persistence import write_json
                        write_json(layout_path, layout)
                        worker_mod.start_worker(self.bp_dir, slot_index, self.socketio)
