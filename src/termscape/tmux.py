"""Run a scene as a thin tmux pane under your work.

The strip pane marks itself with the pane option @termscape=1 so it can be
found and closed later, and exits on its own once it is the only pane left in
its window (so closing your work pane also cleans up the strip).
"""

import os
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path

PANE_OPTION = "@termscape"


def tmux(*args):
    """Run a tmux command and return stdout, or "" if tmux fails."""
    try:
        return subprocess.run(["tmux", *args], capture_output=True, text=True,
                              timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def require_tmux():
    if not shutil.which("tmux"):
        sys.exit("termscape: the strip needs tmux (macOS: brew install tmux, "
                 "Debian/Ubuntu: apt install tmux)")


def scene_command(theme, fps, mode="--strip"):
    """Shell command that runs a scene (strip or screensaver mode) with this same Python."""
    if os.sep in theme or theme.endswith(".toml"):
        theme = str(Path(theme).expanduser().resolve())
    args = [sys.executable, "-m", "termscape", mode, "--theme", theme]
    if fps:
        args += ["--fps", str(fps)]
    # Make the package importable even when running from a source checkout.
    pkg_parent = str(Path(__file__).resolve().parent.parent)
    return f"PYTHONPATH={shlex.quote(pkg_parent)} exec {shlex.join(args)}"


def strip_panes(target):
    out = tmux("list-panes", "-t", target, "-F", "#{pane_id} #{" + PANE_OPTION + "}")
    return [line.split()[0] for line in out.splitlines() if line.endswith(" 1")]


def close_strips(target):
    for pane in strip_panes(target):
        tmux("kill-pane", "-t", pane)


def open_strip(target, height, cmd):
    # -f: full window width, -d: keep focus on the work pane.
    tmux("split-window", "-v", "-f", "-d", "-l", str(height), "-t", target, cmd)


def mark_self():
    pane = os.environ.get("TMUX_PANE")
    if pane:
        tmux("set-option", "-p", "-t", pane, PANE_OPTION, "1")
    return pane


def alone(pane):
    return tmux("display-message", "-p", "-t", pane, "#{window_panes}") == "1"


def strip(theme, height, fps, command):
    """Entry point for `termscape strip`. Returns an exit status."""
    require_tmux()
    cmd = scene_command(theme, fps)
    if command and command[0] == "--":
        command = command[1:]

    if not os.environ.get("TMUX"):
        # Start a new session: your shell (or the command) on top, the strip below.
        session = ["tmux", "new-session", "-c", os.getcwd()]
        if command:
            session.append(shlex.join(command))
        os.execvp("tmux", session + [";", "split-window", "-v", "-f", "-d",
                                     "-l", str(height), "-c", os.getcwd(), cmd])

    here = os.environ.get("TMUX_PANE", "")
    if not command:
        if strip_panes(here):
            close_strips(here)
        else:
            open_strip(here, height, cmd)
        return 0

    opened = not strip_panes(here)
    if opened:
        open_strip(here, height, cmd)
    # Let Ctrl-C reach the command without killing this wrapper, so the strip
    # is still closed afterwards. A Python handler (unlike SIG_IGN) is reset
    # to the default in the child on exec.
    signal.signal(signal.SIGINT, lambda *_: None)
    try:
        status = subprocess.call(command)
    except FileNotFoundError:
        print(f"termscape: command not found: {command[0]}", file=sys.stderr)
        status = 127
    if opened:
        close_strips(here)
    return status


def screensaver(after, theme, disable):
    """Use tmux's idle lock to show a full-screen scene; any key returns to work."""
    require_tmux()
    if not os.environ.get("TMUX"):
        sys.exit("termscape: run this inside tmux (it configures the running tmux server)")
    if disable:
        tmux("set-option", "-g", "lock-after-time", "0")
        print("Screensaver off. Remove the termscape lines from ~/.tmux.conf if you added them.")
        return 0
    cmd = scene_command(theme, None, mode="--screensaver")
    tmux("set-option", "-g", "lock-command", cmd)
    tmux("set-option", "-g", "lock-after-time", str(after))
    print(f"Screensaver on: after {after}s idle tmux shows the scene; press any key to return.")
    print("To keep it after tmux restarts, add to ~/.tmux.conf:")
    print(f"  set -g lock-command {shlex.quote(cmd)}")
    print(f"  set -g lock-after-time {after}")
    return 0


def off():
    require_tmux()
    if not os.environ.get("TMUX"):
        sys.exit("termscape: not inside tmux")
    close_strips(os.environ.get("TMUX_PANE", ""))
    return 0
