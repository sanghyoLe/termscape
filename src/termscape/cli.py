"""Command-line interface.

  termscape [--theme NAME|FILE] [--fps N] [--no-pet]   full-screen scene
  termscape strip [--theme ...] [--height N] [COMMAND ...]
  termscape off                                        close the strip in this tmux window
  termscape themes | check FILE...                     list / validate themes
  termscape connect claude|codex|all                   let the pet follow your coding agent
  termscape disconnect claude|codex|all
  termscape screensaver [--after SECONDS] [--off]      tmux idle screensaver
  termscape ping EVENT [...]                           send an event to running scenes

Internal (called by agents): termscape hook claude|codex, termscape statusline.
"""

import sys

if sys.version_info < (3, 11):
    sys.exit("termscape needs Python 3.11 or newer (found %d.%d)" % sys.version_info[:2])

import argparse
import os
import time

from . import __version__
from . import theme as themes
from . import tmux
from .text import text_width

KEYS_HELP = "q quit  space event  t next theme  p pause  r reshuffle"
AGENTS = ("claude", "codex")


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def build_parser():
    default_theme = os.environ.get("TERMSCAPE_THEME", "night")
    p = argparse.ArgumentParser(
        prog="termscape",
        description="Ambient ASCII scenes for your terminal.",
        epilog="Run `termscape strip claude` to work under a scene, and "
               "`termscape connect claude` to hatch a pet that grows with the context window.")
    p.add_argument("--version", action="version", version=f"termscape {__version__}")
    p.add_argument("--theme", default=default_theme,
                   help=f"theme name, 'random', or path to a .toml file (default: {default_theme})")
    p.add_argument("--fps", type=float, help="frames per second (default: 20, strip: 10)")
    p.add_argument("--no-pet", action="store_true", default=os.environ.get("TERMSCAPE_PET") == "0",
                   help="never show the pet (env TERMSCAPE_PET=0)")
    p.add_argument("--strip", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--screensaver", action="store_true", help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    s = sub.add_parser("strip", help="show the scene in a thin tmux pane under your work",
                       description="Inside tmux: toggle the strip in this window, or run COMMAND "
                                   "with the strip open. Outside tmux: start a new tmux session "
                                   "with the strip (running COMMAND on top if given).")
    s.add_argument("--theme", default=argparse.SUPPRESS, help="theme name or file")
    s.add_argument("--fps", type=float, default=argparse.SUPPRESS)
    s.add_argument("--height", type=int, default=_env_int("TERMSCAPE_HEIGHT", 5),
                   help="strip height in rows (default: 5, env TERMSCAPE_HEIGHT)")
    s.add_argument("command", nargs=argparse.REMAINDER, help="command to run above the strip")

    sub.add_parser("off", help="close the strip in the current tmux window")
    sub.add_parser("themes", help="list available themes")
    c = sub.add_parser("check", help="validate theme files")
    c.add_argument("files", nargs="+")

    for name, text in (("connect", "install hooks so the pet follows a coding agent"),
                       ("disconnect", "remove the hooks installed by connect")):
        cp = sub.add_parser(name, help=text)
        cp.add_argument("agent", choices=AGENTS + ("all",))

    ss = sub.add_parser("screensaver", help="show a scene when tmux has been idle")
    ss.add_argument("--after", type=int, default=300, help="idle seconds before it starts (default 300)")
    ss.add_argument("--theme", default=argparse.SUPPRESS)
    ss.add_argument("--off", action="store_true", help="turn the screensaver off")

    pg = sub.add_parser("ping", help="send an event to running scenes (for scripts and testing)")
    pg.add_argument("event", help="e.g. working, waiting, done, compact, idle, end")
    pg.add_argument("--source", default="cli", help="what sent it (default: cli)")
    pg.add_argument("--session")
    pg.add_argument("--context", type=float, help="context fraction 0..1")
    pg.add_argument("--tokens", type=int)

    hk = sub.add_parser("hook")
    hk.add_argument("agent", choices=AGENTS)
    sl = sub.add_parser("statusline")
    sl.add_argument("--wrap", help="existing status line command to run and keep")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cmd = args.cmd
    if cmd == "hook":
        from .hooks import handle_hook
        sys.exit(handle_hook(args.agent))
    if cmd == "statusline":
        from .hooks import handle_statusline
        sys.exit(handle_statusline(args.wrap))
    if cmd == "strip":
        sys.exit(tmux.strip(args.theme, max(2, args.height), args.fps, args.command))
    if cmd == "off":
        sys.exit(tmux.off())
    if cmd == "themes":
        sys.exit(list_themes())
    if cmd == "check":
        sys.exit(check(args.files))
    if cmd in ("connect", "disconnect"):
        from . import hooks
        for agent in AGENTS if args.agent == "all" else (args.agent,):
            (hooks.connect if cmd == "connect" else hooks.disconnect)(agent)
        if cmd == "connect":
            print("Restart running agents if the pet does not appear. "
                  "Then: termscape strip claude")
        sys.exit(0)
    if cmd == "screensaver":
        sys.exit(tmux.screensaver(args.after, args.theme, args.off))
    if cmd == "ping":
        from . import events
        events.emit(args.event, source=args.source, session=args.session,
                    context=args.context, tokens=args.tokens)
        sys.exit(0)
    fps = args.fps or (10.0 if args.strip else 20.0)
    sys.exit(run(args.theme, fps, strip=args.strip, pet=not args.no_pet,
                 screensaver=args.screensaver))


def list_themes():
    user = themes.user_dir()
    for name, path in themes.available().items():
        try:
            desc = themes.load(path).description
        except themes.ThemeError as e:
            desc = f"(broken: {e})"
        where = " [user]" if path.parent == user else ""
        print(f"{name:<10}{where} {desc}")
    print(f"\nAdd your own: {user}/<name>.toml")
    return 0


def check(files):
    failed = 0
    for f in files:
        try:
            t = themes.load(f)
        except themes.ThemeError as e:
            print(f"error: {e}")
            failed += 1
            continue
        tiles = len(t.ground.tiles) if t.ground else 0
        print(f"ok: {f} ({t.name}: {len(t.actors)} actors, {tiles} ground tiles)")
    return 1 if failed else 0


def run(theme_arg, fps, strip=False, pet=True, screensaver=False):
    try:
        theme = themes.load(themes.resolve(theme_arg))
    except themes.ThemeError as e:
        sys.exit(f"termscape: {e}")
    import curses
    try:
        curses.wrapper(_loop, theme, fps, strip, pet, screensaver)
    except KeyboardInterrupt:
        pass
    return 0


class CursesCanvas:
    def __init__(self, scr):
        import curses
        self.error = curses.error
        self.scr = scr
        self.h, self.w = scr.getmaxyx()

    def size(self):
        self.h, self.w = self.scr.getmaxyx()
        return self.h, self.w

    def put(self, y, x, ch, attr=0):
        if 0 <= y < self.h and 0 <= x < self.w:
            if not ch.isascii() and x == self.w - 1 and text_width(ch) == 2:
                return  # a wide character would not fit in the last column
            try:
                self.scr.addstr(y, x, ch, attr)
            except self.error:
                pass  # writing the bottom-right cell raises after drawing the character

    def text(self, y, x, s, attr=0):
        for i, ch in enumerate(s):
            self.put(y, x + i, ch, attr)


def _loop(scr, theme, fps, strip, show_pet, screensaver):
    import curses
    from . import events
    from .colors import CursesPalette
    from .engine import Scene
    from .pet import Pet

    try:
        curses.curs_set(0)
    except curses.error:
        pass
    scr.nodelay(True)
    palette = CursesPalette(theme.background)
    scr.bkgd(" ", palette.background_attr())
    canvas = CursesCanvas(scr)
    scene = Scene(canvas, palette, theme)
    pane = tmux.mark_self() if strip else None

    pet = Pet()
    reader = None
    if show_pet:
        reader = events.Reader(events.window_key())
        for ev in reader.backlog:
            pet.apply(ev, live=False)

    banner = f" {theme.name} | {KEYS_HELP} " if not (strip or screensaver) else ""
    banner_until = 4.0
    paused = False
    last = time.monotonic()
    next_check = last + 2.0
    next_poll = last

    while True:
        key = scr.getch()
        if screensaver and key not in (-1, curses.KEY_RESIZE):
            return
        if key in (ord("q"), ord("Q")):
            return
        if key == ord("p"):
            paused = not paused
        elif key == ord("r"):
            scene.reset()
            banner_until = 0
        elif key == ord(" "):
            scene.random_event()
        elif key == ord("t"):
            theme = _next_theme(theme)
            palette.set_background(theme.background)
            scr.bkgd(" ", palette.background_attr())
            scene.set_theme(theme)
            banner, banner_until = f" {theme.name} ", 2.0

        if scr.getmaxyx() != (scene.h, scene.w):
            scene.reset()

        now = time.monotonic()
        dt = min(now - last, 0.1)
        last = now
        if pane and now >= next_check:
            next_check = now + 2.0
            if tmux.alone(pane):
                return
        if reader and now >= next_poll:
            next_poll = now + 0.2
            for ev in reader.poll():
                pet.apply(ev)

        scr.erase()
        if not paused:
            scene.update(dt)
        scene.draw()
        if show_pet:
            pet.draw(canvas, palette, scene.h, scene.w, time.time(), 0 if paused else dt)
        if banner and scene.t < banner_until:
            canvas.text(0, 0, banner[: scene.w], palette.attr("magenta reverse"))
        scr.refresh()
        time.sleep(max(0.0, 1 / fps - (time.monotonic() - now)))


def _next_theme(current):
    paths = list(themes.available().values())
    if not paths:
        return current
    names = [p.stem for p in paths]
    start = names.index(current.source.stem) + 1 if current.source and current.source.stem in names else 0
    for i in range(len(paths)):
        try:
            return themes.load(paths[(start + i) % len(paths)])
        except themes.ThemeError:
            continue
    return current
