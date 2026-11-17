# termscape

Ambient ASCII scenes for your terminal — full-screen, or as a thin animated strip
under the shell, editor or coding agent you are actually working in.

```
       *              +                          *(@)
                       *                                 <=(o)=>
*                 *  ______                                (____)        *
|___  ____          |# . # |  _______  ____                  __|___    __|___
# . ||#  #|  |# . .||. . # | |# . . #||.  .||# # .| |. . #| |# . . |  |. # # |
```

- **Strip mode:** a 3–8 row scene at the bottom of a tmux window, so you can keep
  working above it, including inside Claude Code, Codex, vim or htop.
- **Four built-in themes:** `night` (city skyline, meteors, UFO, rockets), `ocean`,
  `forest`, `snow`.
- **Your own themes:** a theme is a small TOML file of ASCII art plus how each
  piece moves. No code needed; see [docs/THEMES.md](docs/THEMES.md).
- **No dependencies:** pure Python standard library.

## Install

Requires Python 3.11+ on macOS or Linux. Strip mode also needs
[tmux](https://github.com/tmux/tmux) (`brew install tmux` / `apt install tmux`).

```sh
pipx install git+https://github.com/sanghyoLe/termscape.git
# or: uv tool install git+https://github.com/sanghyoLe/termscape.git
```

To update later, run the same command with `pipx install --force ...` (or `uv tool upgrade termscape`).

## Use

```sh
termscape                         # full screen
termscape --theme ocean           # pick a theme ('random' works too)
termscape themes                  # list themes

termscape strip                   # new tmux session with the strip at the bottom
termscape strip claude            # run a command above the strip; both close when it exits
termscape strip codex
```

Inside tmux, `termscape strip` toggles the strip in the current window and
`termscape off` closes it. Closing your work pane also closes the strip.

Keys (the strip reacts when you click into it): `q` quit, `space` random event,
`t` next theme, `p` pause, `r` reshuffle the scene.

Settings:

| | Flag | Environment |
|---|---|---|
| Theme | `--theme NAME\|FILE` | `TERMSCAPE_THEME` |
| Strip height | `strip --height N` | `TERMSCAPE_HEIGHT` (default 5) |
| Frame rate | `--fps N` | (default 20, strip 10) |

Tip: add `alias ts='termscape strip'` to your shell config.

## A pet that grows with your context window

```sh
termscape connect claude      # or: codex, all
termscape strip claude
```

`connect` adds hooks (and, for Claude Code, a status line) so a little creature
hatches in your strip and grows as the agent's context window fills up:

```
 _       .-.       .--.       .---.         .---.           .-------.
(_)     (o-o)     (o  o)     ( o o )       / o o \         /  o   o  \
                   `--'       `---'       (   -   )       (     -     )
                                           `-...-'         `-.......-'
egg     baby 5%    kid 20%    teen 45%     adult 70%        giant 90%
```

It wanders around while the agent works, shows `?` when the agent is waiting
for you (permission prompts), jumps when a turn finishes, falls asleep after a
while, and shouts `full!` past 90%. When the context is compacted or a new
session starts it shrinks back to an egg in a puff of smoke. Each tmux window
has its own pet that follows only the agent running in that window.

- Claude Code hooks run with `"async": true`, so they never slow the agent down.
  The status line provides the exact context percentage; if you already have a
  status line, it is wrapped and its output is left unchanged.
- Codex hooks go to `~/.codex/hooks.json`; context usage comes from the session log.
- Your previous settings file is saved next to it as `*.termscape-backup`, and
  `termscape disconnect claude` removes exactly what `connect` added.
- `--no-pet` or `TERMSCAPE_PET=0` hides the pet. Scripts can drive it too:
  `termscape ping working --source me --context 0.4`.

## Screensaver

```sh
termscape screensaver --after 300    # inside tmux; --off to disable
```

After five idle minutes tmux shows a full-screen scene; any key brings your
work back. The command prints the two lines to add to `~/.tmux.conf` to keep it.

## Make a theme

```toml
# ~/.config/termscape/themes/pond.toml
name = "pond"

[sky]
chars = [" ", ".", "o"]
colors = "cyan dim"

[[actor]]
art = "><>"
palette = ["yellow", "cyan", "magenta"]
rate = 0.5

[[actor]]
motion = "rise"
art = "o"
color = "cyan"
sway = 0.5
```

```sh
termscape check ~/.config/termscape/themes/pond.toml
termscape --theme pond
```

The full format (motions, ground tiles with blinking windows, colors, strip-only
art) is documented in [docs/THEMES.md](docs/THEMES.md). New themes are very
welcome as pull requests.

## Development

```sh
python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m termscape --theme snow
```

The engine (`engine.py`) only needs a canvas with `size()`/`put()` and a palette
with `attr()`, so the tests run every built-in theme at several screen sizes
without a terminal.

## License

MIT
