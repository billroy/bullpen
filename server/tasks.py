"""Task ticket CRUD."""

import os
import re
import secrets
import string
from datetime import datetime, timezone

from server.persistence import (
    ensure_within,
    read_frontmatter,
    write_frontmatter,
)

# Lexicographically ordered base62: 0-9, A-Z, a-z
BASE62 = string.digits + string.ascii_uppercase + string.ascii_lowercase


def _base62_encode(n, length=4):
    """Encode integer n as base62 string of given length."""
    result = []
    for _ in range(length):
        result.append(BASE62[n % 62])
        n //= 62
    return "".join(reversed(result))


def _random_suffix(length=4):
    """Generate random base62 suffix."""
    return "".join(secrets.choice(BASE62) for _ in range(length))


def slugify(title):
    """Convert title to URL-safe slug."""
    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s-]+", "-", s)
    s = s.strip("-")
    return s[:60] if s else "task"


def generate_slug(title):
    """Generate a unique slug: slugified-title-XXXX."""
    return f"{slugify(title)}-{_random_suffix()}"


# --- Fractional indexing ---

MIDPOINT_BASE = BASE62


def generate_order_key():
    """Generate an initial order key (midpoint of keyspace)."""
    return "V"


def midpoint_key(a, b):
    """Generate a key between a and b lexicographically.

    a and b are base62 strings. Empty string means "no bound".
    """
    if not a and not b:
        return "V"

    # Use character-by-character approach
    idx = BASE62
    if not a:
        # Generate key before b: take first char's midpoint with '0'
        b0 = idx.index(b[0])
        if b0 > 1:
            return idx[b0 // 2]
        # b starts with '0' or '1', need to go deeper
        return idx[0] + midpoint_key("", b[1:] if len(b) > 1 else "V")
    if not b:
        # Generate key after a: take first char's midpoint with 'z'
        a0 = idx.index(a[0])
        z0 = len(idx) - 1
        if z0 - a0 > 1:
            return idx[(a0 + z0) // 2]
        # a starts near 'z', need to go deeper
        return a[0] + midpoint_key(a[1:] if len(a) > 1 else "", "")
    # Both bounds exist
    # Pad shorter to same length for comparison
    max_len = max(len(a), len(b))
    a_pad = a.ljust(max_len, BASE62[0])
    b_pad = b.ljust(max_len, BASE62[0])

    for i in range(max_len):
        ai = idx.index(a_pad[i])
        bi = idx.index(b_pad[i])
        if ai < bi:
            if bi - ai > 1:
                # There's room between these chars
                return a_pad[:i] + idx[(ai + bi) // 2]
            else:
                # Adjacent chars, go one level deeper
                return a_pad[:i + 1] + midpoint_key(a_pad[i + 1:], "")
        # ai == bi, continue to next character

    # All chars equal — extend with midpoint
    return a + "V"


# --- CRUD ---

def _tasks_dir(bp_dir):
    return os.path.join(bp_dir, "tasks")


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_order_key(bp_dir):
    """Generate an order key that sorts after all existing inbox tasks."""
    tasks_dir = _tasks_dir(bp_dir)
    if not os.path.isdir(tasks_dir):
        return generate_order_key()

    # Find the highest order key among existing tasks
    max_key = ""
    for fname in os.listdir(tasks_dir):
        if fname.endswith(".md"):
            path = os.path.join(tasks_dir, fname)
            meta, _, _ = read_frontmatter(path)
            key = meta.get("order", "")
            if key > max_key:
                max_key = key

    if not max_key:
        return generate_order_key()

    return midpoint_key(max_key, "")


def create_task(bp_dir, title, description="", task_type="task", priority="normal", tags=None):
    """Create a new task ticket. Returns the task dict."""
    slug = generate_slug(title)
    now = _now_iso()

    meta = {
        "title": title,
        "status": "inbox",
        "type": task_type,
        "priority": priority,
        "assigned_to": "",
        "created_at": now,
        "updated_at": now,
        "order": _next_order_key(bp_dir),
        "tags": tags or [],
    }

    body = ""
    if description:
        body = f"\n## Description\n\n{description}\n"

    path = os.path.join(_tasks_dir(bp_dir), f"{slug}.md")
    write_frontmatter(path, meta, body, slug)

    return {**meta, "id": slug, "body": body}


def read_task(bp_dir, task_id):
    """Read a single task by ID. Returns task dict or None."""
    path = os.path.join(_tasks_dir(bp_dir), f"{task_id}.md")
    if not os.path.exists(path):
        return None
    ensure_within(path, _tasks_dir(bp_dir))
    meta, body, slug = read_frontmatter(path)
    return {**meta, "id": slug or task_id, "body": body}


def update_task(bp_dir, task_id, fields):
    """Update task fields. Returns updated task dict."""
    path = os.path.join(_tasks_dir(bp_dir), f"{task_id}.md")
    ensure_within(path, _tasks_dir(bp_dir))
    meta, body, slug = read_frontmatter(path)

    # Update body if provided
    if "body" in fields:
        body = fields.pop("body")

    # Merge fields
    for k, v in fields.items():
        if k != "id":  # don't store id in frontmatter
            meta[k] = v

    meta["updated_at"] = _now_iso()
    write_frontmatter(path, meta, body, slug)

    return {**meta, "id": slug or task_id, "body": body}


def delete_task(bp_dir, task_id):
    """Delete a task by ID."""
    path = os.path.join(_tasks_dir(bp_dir), f"{task_id}.md")
    ensure_within(path, _tasks_dir(bp_dir))
    if os.path.exists(path):
        os.remove(path)


def clear_task_output(bp_dir, task_id):
    """Remove content under ## Agent Output heading."""
    path = os.path.join(_tasks_dir(bp_dir), f"{task_id}.md")
    ensure_within(path, _tasks_dir(bp_dir))
    meta, body, slug = read_frontmatter(path)

    # Remove everything from ## Agent Output onward
    marker = "## Agent Output"
    idx = body.find(marker)
    if idx >= 0:
        body = body[:idx].rstrip() + "\n"

    meta["updated_at"] = _now_iso()
    write_frontmatter(path, meta, body, slug)

    return {**meta, "id": slug or task_id, "body": body}


def list_tasks(bp_dir):
    """List all tasks, sorted by order key."""
    tasks_dir = _tasks_dir(bp_dir)
    if not os.path.isdir(tasks_dir):
        return []

    tasks = []
    for fname in os.listdir(tasks_dir):
        if fname.endswith(".md"):
            path = os.path.join(tasks_dir, fname)
            meta, body, slug = read_frontmatter(path)
            tasks.append({**meta, "id": slug or fname[:-3], "body": body})

    priority_weight = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    tasks.sort(key=lambda t: (priority_weight.get(t.get("priority", "normal"), 2), t.get("order", "")))
    return tasks
