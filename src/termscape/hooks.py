"""Connect coding agents to termscape.

`termscape connect claude|codex` registers `termscape hook <agent>` as a hook
command; each hook call reads the agent's JSON payload from stdin and emits a
termscape event (working / waiting / done / compact / ...) with the current
context usage, which the pet reacts to.

For Claude Code, `termscape statusline` is also installed as the status line
(wrapping any existing one), because the status line input carries the exact
context-window percentage; hooks only see the transcript, from which tokens are
estimated.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import events

HOOK_MARK = "termscape hook"
STATUS_MARK = "termscape statusline"

CLAUDE_HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop",
                      "Notification", "PreCompact", "SessionEnd")
CLAUDE_EVENT_MAP = {"UserPromptSubmit": "working", "PostToolUse": "working",
                    "Stop": "done", "PreCompact": "compact", "SessionEnd": "end"}
# Notifications that mean "the agent is blocked until you answer".
CLAUDE_WAITING = ("permission_prompt", "elicitation_dialog")

CODEX_EVENT_MAP = {"SessionStart": "start", "UserPromptSubmit": "working",
                   "PostToolUse": "working", "PermissionRequest": "waiting",
                   "Stop": "done", "Interrupt": "idle"}


# ---------- reading transcripts ----------

def _lines_from_end(path, max_bytes=512 * 1024):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read()
    lines = data.split(b"\n")
    if size > max_bytes:
        lines = lines[1:]  # first line is probably cut in half
    return reversed(lines)


def claude_tokens(transcript):
    """Context tokens of the latest main-thread response in a Claude Code transcript."""
    for line in _lines_from_end(transcript):
        if b'"usage"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        msg = entry.get("message")
        if entry.get("isSidechain") or not isinstance(msg, dict):
            continue
        usage = msg.get("usage")
        if isinstance(usage, dict):
            return sum(int(usage.get(k) or 0) for k in
                       ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return None


def codex_context(transcript):
    """(tokens, context window size) from the latest token_count event of a Codex rollout."""
    for line in _lines_from_end(transcript):
        if b'"token_count"' not in line:
            continue
        try:
            info = json.loads(line)["payload"]["info"]
            return int(info["last_token_usage"]["input_tokens"]), info.get("model_context_window")
        except (ValueError, KeyError, TypeError):
            continue
    return None, None


def codex_transcript(payload):
    if payload.get("transcript_path"):
        return payload["transcript_path"]
    session = payload.get("session_id")
    if not session:
        return None
    root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    found = sorted(root.glob(f"*/*/*/*{session}.jsonl"), key=lambda p: p.stat().st_mtime)
    return str(found[-1]) if found else None


# ---------- hook and status line handlers ----------

def handle_hook(agent, stream=None):
    """Turn one hook payload into an event. Never fails: a broken hook must not disturb the agent."""
    try:
        payload = json.load(stream or sys.stdin)
        if not isinstance(payload, dict):
            return 0
        name = payload.get("hook_event_name", "")
        fields = {"source": agent, "session": payload.get("session_id")}
        if agent == "claude":
            if name == "SessionStart":
                event = "compact" if payload.get("source") == "compact" else "start"
                fields["tokens"] = payload.get("context_tokens")
            elif name == "Notification":
                if payload.get("notification_type") not in CLAUDE_WAITING:
                    return 0
                event = "waiting"
            else:
                event = CLAUDE_EVENT_MAP.get(name)
            if event in ("working", "done") and payload.get("transcript_path"):
                fields["tokens"] = claude_tokens(payload["transcript_path"])
        else:
            event = CODEX_EVENT_MAP.get(name)
            transcript = codex_transcript(payload) if event else None
            if transcript:
                fields["tokens"], fields["size"] = codex_context(transcript)
        if event:
            events.emit(event, **fields)
    except Exception:  # noqa: BLE001 - see docstring
        pass
    return 0


def _last_status_path():
    return events.log_path().with_name("statusline-last.json")


def handle_statusline(wrapped=None):
    """Claude Code status line: forward exact context usage, print a status line."""
    raw = sys.stdin.read()
    out = ""
    if wrapped:
        try:
            out = subprocess.run(wrapped, shell=True, input=raw, capture_output=True,
                                 text=True, timeout=5).stdout.rstrip("\n")
        except (OSError, subprocess.SubprocessError):
            out = ""
    pct = None
    try:
        data = json.loads(raw)
        cw = data.get("context_window") or {}
        pct = cw.get("used_percentage")
        if isinstance(pct, (int, float)):
            session = data.get("session_id")
            key = [session, round(pct)]
            last = _last_status_path()
            try:
                previous = json.loads(last.read_text())
            except (OSError, ValueError):
                previous = None
            if previous != key:  # only emit when the whole percentage changes
                events.emit("context", source="claude", session=session,
                            context=pct / 100, size=cw.get("context_window_size"))
                last.write_text(json.dumps(key))
    except Exception:  # noqa: BLE001 - the status line must always print
        pass
    if wrapped:
        print(out)
    elif isinstance(pct, (int, float)):
        print(f"ctx {round(pct)}%")
    else:
        print("")
    return 0


# ---------- installing ----------

def claude_settings_path():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


def codex_hooks_path():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "hooks.json"


def base_command():
    exe = shutil.which("termscape")
    return shlex.quote(exe) if exe else shlex.join([sys.executable, "-m", "termscape"])


def _load(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    if not isinstance(data, dict):
        raise SystemExit(f"termscape: {path} does not contain a JSON object; not touching it")
    return data


def _save(path, data):
    backup = None
    if path.exists():
        backup = path.with_name(path.name + ".termscape-backup")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return backup


def _remove_ours(hooks):
    for event in list(hooks):
        groups = []
        for group in hooks[event] if isinstance(hooks[event], list) else []:
            if not isinstance(group, dict):
                groups.append(group)
                continue
            kept = [h for h in group.get("hooks", []) if HOOK_MARK not in str(h.get("command", ""))]
            if kept:
                groups.append({**group, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]


def connect(agent):
    base = base_command()
    if agent == "claude":
        path = claude_settings_path()
        data = _load(path)
        hooks = data.setdefault("hooks", {})
        _remove_ours(hooks)
        for event in CLAUDE_HOOK_EVENTS:
            hooks.setdefault(event, []).append({"hooks": [{
                "type": "command", "command": f"{base} hook claude", "async": True, "timeout": 10}]})
        status = data.get("statusLine")
        note = "status line: installed"
        if isinstance(status, dict) and STATUS_MARK in str(status.get("command", "")):
            note = "status line: already installed"
        elif isinstance(status, dict) and status.get("command"):
            data["statusLine"] = {**status, "command":
                                  f"{base} statusline --wrap {shlex.quote(status['command'])}"}
            note = "status line: wrapped your existing one (its output is unchanged)"
        else:
            data["statusLine"] = {"type": "command", "command": f"{base} statusline"}
    else:
        path = codex_hooks_path()
        data = _load(path)
        hooks = data.setdefault("hooks", {})
        _remove_ours(hooks)
        for event in CODEX_EVENT_MAP:
            hooks.setdefault(event, []).append({"hooks": [{
                "type": "command", "command": f"{base} hook codex", "timeout": 5}]})
        note = None
    backup = _save(path, data)
    print(f"{agent}: hooks added to {path}")
    if note:
        print(f"{agent}: {note}")
    if backup:
        print(f"{agent}: previous file saved as {backup}")


def disconnect(agent):
    path = claude_settings_path() if agent == "claude" else codex_hooks_path()
    if not path.exists():
        print(f"{agent}: nothing to remove ({path} does not exist)")
        return
    data = _load(path)
    if isinstance(data.get("hooks"), dict):
        _remove_ours(data["hooks"])
        if not data["hooks"]:
            del data["hooks"]
    status = data.get("statusLine")
    if agent == "claude" and isinstance(status, dict) and STATUS_MARK in str(status.get("command", "")):
        args = shlex.split(status["command"])
        if "--wrap" in args and args.index("--wrap") + 1 < len(args):
            data["statusLine"] = {**status, "command": args[args.index("--wrap") + 1]}
        else:
            del data["statusLine"]
    backup = _save(path, data)
    print(f"{agent}: termscape hooks removed from {path} (previous file: {backup})")
