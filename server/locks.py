"""Shared threading locks for serializing layout mutations."""

import threading

# Single-writer lock to serialize all layout read-modify-write sequences.
# Used by both socket event handlers (events.py) and background agent
# threads (workers.py) to prevent race conditions.
write_lock = threading.Lock()
