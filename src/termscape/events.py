"""A tiny event bus: writers append JSON lines to a log file, scenes tail it.

Events carry the tmux window they came from, so a strip only reacts to what
happens in its own window. Events sent from outside tmux reach every scene.

Record fields: t (unix time), event (name), window (or absent), plus optional
source ("claude", "codex", ...), session, and context (0..1 fraction of the
model's context window in use).
"""

import json
import os
import time
from pathlib import Path

MAX_BYTES = 256 * 1024  # the log is rotated to events.jsonl.old once it grows past this


def log_path():
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base) / "termscape" / "events.jsonl"


def window_key():
    """Identify the tmux window this process runs in, or None outside tmux."""
    pane = os.environ.get("TMUX_PANE")
    server = os.environ.get("TMUX", "").split(",")[0]
    if not pane or not server:
        return None
    from .tmux import tmux
    window = tmux("display-message", "-p", "-t", pane, "#{window_id}")
    return f"{server}:{window}" if window else None


def emit(event, **fields):
    record = {"t": time.time(), "event": event}
    window = window_key()
    if window:
        record["window"] = window
    record.update({k: v for k, v in fields.items() if v is not None})
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.stat().st_size > MAX_BYTES:
            # Rotate rather than truncate: readers notice the new inode and start over.
            os.replace(path, path.with_name(path.name + ".old"))
    except FileNotFoundError:
        pass
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


class Reader:
    """Follows the event log, yielding events meant for `window`.

    `backlog` holds the matching events already in the log when the reader was
    created, so a scene can restore state (like the pet's size) on startup.
    """

    def __init__(self, window):
        self.path = log_path()
        self.window = window
        self.offset = 0
        self.inode = None
        self.partial = b""
        self.backlog = self.poll()

    def _wanted(self, ev):
        w = ev.get("window")
        return self.window is None or w is None or w == self.window

    def poll(self):
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return []
        size = st.st_size
        if st.st_ino != self.inode or size < self.offset:  # rotated or truncated
            self.inode, self.offset, self.partial = st.st_ino, 0, b""
        if size == self.offset:
            return []
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            data = f.read()
        self.offset += len(data)
        lines = (self.partial + data).split(b"\n")
        self.partial = lines.pop()
        out = []
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and isinstance(ev.get("event"), str) and self._wanted(ev):
                out.append(ev)
        return out
