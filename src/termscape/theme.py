"""Theme files: TOML documents describing a scene's art and how each piece moves.

See docs/THEMES.md for the full format. Loading validates everything up front so
`termscape check` can report mistakes before anything is drawn.
"""

import os
import random
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .colors import ColorError, parse_color
from .text import mirror_char, mirror_row, pad, text_width

MOTIONS = ("drift", "rise", "fall", "streak", "static")
LAYERS = ("back", "front")
ONLY = ("any", "full", "strip")
DIRECTIONS = ("random", "left", "right")

ART_KEYS = {"art", "frames", "color", "colors", "blink", "fps"}
ACTOR_KEYS = ART_KEYS | {
    "name", "motion", "speed", "accel", "rate", "max", "start", "x", "y", "bob",
    "sway", "layer", "only", "palette", "direction", "mirror", "slope", "life",
    "trail", "trail_color",
}
GROUND_KEYS = {"tile", "height", "gap", "floor", "floor_color", "lights",
               "color", "colors", "blink", "fps"}
LIGHT_KEYS = {"on", "off", "on_color", "off_color", "ratio", "rate"}
SKY_KEYS = {"chars", "colors", "density", "speed"}
TOP_KEYS = {"name", "description", "background", "sky", "ground", "actor"}

# Per-motion defaults for actor keys that depend on how the actor moves.
MOTION_DEFAULTS = {
    "drift":  {"speed": (3.0, 8.0), "x": (0.0, 1.0), "y": (0.0, 0.5), "rate": 0.1, "start": 0},
    "rise":   {"speed": (2.0, 4.0), "x": (0.0, 1.0), "y": (0.0, 1.0), "rate": 0.1, "start": 0},
    "fall":   {"speed": (1.0, 3.0), "x": (0.0, 1.0), "y": (0.0, 1.0), "rate": 0.1, "start": 0},
    "streak": {"speed": (40.0, 70.0), "x": (0.3, 1.1), "y": (0.0, 0.3), "rate": 0.3, "start": 0},
    "static": {"speed": (0.0, 0.0), "x": (0.5, 0.5), "y": (0.0, 0.0), "rate": 0.0, "start": 1},
}
DEFAULT_TRAIL = ("=", "=", "-", "-", "-", "-", ".")


class ThemeError(Exception):
    pass


@dataclass(frozen=True)
class Art:
    frames: tuple  # tuple of frames; each frame is a tuple of rows padded to `width`
    width: int
    height: int
    fps: float
    color: str
    colors: dict  # single char -> color spec
    blink: dict   # single char -> char it alternates with

    def mirrored(self):
        return Art(
            frames=tuple(tuple(mirror_row(r) for r in f) for f in self.frames),
            width=self.width, height=self.height, fps=self.fps, color=self.color,
            colors={mirror_char(k): v for k, v in self.colors.items()},
            blink={mirror_char(k): mirror_char(v) for k, v in self.blink.items()},
        )


@dataclass(frozen=True)
class Actor:
    name: str
    art: Art
    mirrored: Art | None
    motion: str
    speed: tuple
    accel: float
    rate: float
    max: int
    start: int
    x: tuple
    y: tuple
    bob: float
    sway: float
    layer: str
    only: str
    palette: tuple
    direction: str
    slope: tuple
    life: tuple
    trail: tuple
    trail_color: tuple


@dataclass(frozen=True)
class Lights:
    on: str
    off: str
    on_color: str
    off_color: str
    ratio: float
    rate: float


@dataclass(frozen=True)
class Ground:
    tiles: tuple
    height: float
    gap: tuple
    floor: str | None
    floor_color: str
    lights: Lights | None


@dataclass(frozen=True)
class Sky:
    chars: tuple
    colors: tuple
    density: float
    speed: tuple


@dataclass(frozen=True)
class Theme:
    name: str
    description: str
    background: str | None
    sky: Sky | None
    ground: Ground | None
    actors: tuple
    source: Path | None = None


# ---------- validation helpers ----------

def _table(v, where):
    if not isinstance(v, dict):
        raise ThemeError(f"{where}: expected a table")
    return v


def _keys(tbl, allowed, where):
    _table(tbl, where)
    extra = sorted(set(tbl) - allowed)
    if extra:
        raise ThemeError(f"{where}: unknown key(s) {', '.join(extra)} "
                         f"(allowed: {', '.join(sorted(allowed))})")


def _num(v, where, lo=None, hi=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ThemeError(f"{where}: expected a number, got {v!r}")
    if lo is not None and v < lo:
        raise ThemeError(f"{where}: must be >= {lo}, got {v}")
    if hi is not None and v > hi:
        raise ThemeError(f"{where}: must be <= {hi}, got {v}")
    return float(v)


def _int(v, where, lo=0):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ThemeError(f"{where}: expected a whole number, got {v!r}")
    if v < lo:
        raise ThemeError(f"{where}: must be >= {lo}, got {v}")
    return v


def _range(v, where, lo=None):
    """A number or a [min, max] pair -> (min, max)."""
    if isinstance(v, list):
        if len(v) != 2:
            raise ThemeError(f"{where}: expected a number or [min, max]")
        a, b = _num(v[0], where, lo), _num(v[1], where, lo)
        if a > b:
            raise ThemeError(f"{where}: min {a} is larger than max {b}")
        return (a, b)
    n = _num(v, where, lo)
    return (n, n)


def _color(v, where):
    try:
        parse_color(v)
    except ColorError as e:
        raise ThemeError(f"{where}: {e}") from None
    return v


def _choice(v, options, where):
    if v not in options:
        raise ThemeError(f"{where}: expected one of {', '.join(options)}, got {v!r}")
    return v


def _char(v, where, allow_space=True):
    if not isinstance(v, str) or text_width(v) != 1 or len(v) != 1:
        raise ThemeError(f"{where}: expected a single one-cell character, got {v!r}")
    if not allow_space and v == " ":
        raise ThemeError(f"{where}: a space is not allowed here")
    return v


def _char_map(v, where, values_are_colors):
    out = {}
    for k, val in _table(v, where).items():
        _char(k, f"{where} key", allow_space=False)
        out[k] = _color(val, f"{where}.{k}") if values_are_colors else _char(val, f"{where}.{k}")
    return out


def _rows(text, where):
    if not isinstance(text, str):
        raise ThemeError(f"{where}: expected a string")
    if "\t" in text:
        raise ThemeError(f"{where}: tabs are not allowed in art; use spaces")
    rows = [r.rstrip() for r in text.rstrip("\n").split("\n")]
    if not any(rows):
        raise ThemeError(f"{where}: art is empty")
    return rows


def _art(tbl, where, color="white", colors=None, blink=None, fps=2.0):
    if ("art" in tbl) == ("frames" in tbl):
        raise ThemeError(f"{where}: give exactly one of 'art' or 'frames'")
    if "art" in tbl:
        texts = [tbl["art"]]
    else:
        texts = tbl["frames"]
        if not isinstance(texts, list) or not texts:
            raise ThemeError(f"{where}.frames: expected a non-empty list of strings")
    frames = [_rows(t, f"{where}.frames[{i}]" if "frames" in tbl else f"{where}.art")
              for i, t in enumerate(texts)]
    height = max(len(f) for f in frames)
    width = max(text_width(r) for f in frames for r in f)
    padded = tuple(tuple(pad(r, width) for r in f) + (" " * width,) * (height - len(f))
                   for f in frames)
    merged_colors = dict(colors or {})
    merged_colors.update(_char_map(tbl.get("colors", {}), f"{where}.colors", True))
    merged_blink = dict(blink or {})
    merged_blink.update(_char_map(tbl.get("blink", {}), f"{where}.blink", False))
    return Art(
        frames=padded, width=width, height=height,
        fps=_num(tbl.get("fps", fps), f"{where}.fps", lo=0),
        color=_color(tbl.get("color", color), f"{where}.color"),
        colors=merged_colors, blink=merged_blink,
    )


def _color_list(v, n, where):
    """A single color or a list of colors -> tuple of n colors (last one repeats)."""
    items = v if isinstance(v, list) else [v]
    if not items:
        raise ThemeError(f"{where}: expected a color or a non-empty list of colors")
    items = [_color(c, f"{where}[{i}]") for i, c in enumerate(items)]
    return tuple(items[min(i, len(items) - 1)] for i in range(n))


# ---------- sections ----------

def _actor(tbl, where):
    _keys(tbl, ACTOR_KEYS, where)
    motion = _choice(tbl.get("motion", "drift"), MOTIONS, f"{where}.motion")
    d = MOTION_DEFAULTS[motion]
    art = _art(tbl, where)
    mirror = tbl.get("mirror", True)
    if not isinstance(mirror, bool):
        raise ThemeError(f"{where}.mirror: expected true or false")
    trail = tuple(_char(c, f"{where}.trail") for c in tbl.get("trail", DEFAULT_TRAIL))
    if motion == "streak" and not trail:
        raise ThemeError(f"{where}.trail: a streak needs at least one trail character")
    return Actor(
        name=str(tbl.get("name", "actor")),
        art=art,
        mirrored=art.mirrored() if mirror and motion == "drift" else None,
        motion=motion,
        speed=_range(tbl.get("speed", list(d["speed"])), f"{where}.speed", lo=0),
        accel=_num(tbl.get("accel", 0), f"{where}.accel"),
        rate=_num(tbl.get("rate", d["rate"]), f"{where}.rate", lo=0),
        max=_int(tbl.get("max", 3), f"{where}.max", lo=1),
        start=_int(tbl.get("start", d["start"]), f"{where}.start"),
        x=_range(tbl.get("x", list(d["x"])), f"{where}.x"),
        y=_range(tbl.get("y", list(d["y"])), f"{where}.y"),
        bob=_num(tbl.get("bob", 0), f"{where}.bob", lo=0),
        sway=_num(tbl.get("sway", 0), f"{where}.sway", lo=0),
        layer=_choice(tbl.get("layer", "front"), LAYERS, f"{where}.layer"),
        only=_choice(tbl.get("only", "any"), ONLY, f"{where}.only"),
        palette=tuple(_color(c, f"{where}.palette") for c in tbl.get("palette", [])),
        direction=_choice(tbl.get("direction", "left" if motion == "streak" else "random"),
                          DIRECTIONS, f"{where}.direction"),
        slope=_range(tbl.get("slope", [0.2, 0.4]), f"{where}.slope", lo=0),
        life=_range(tbl.get("life", [0.6, 1.6]), f"{where}.life", lo=0),
        trail=trail,
        trail_color=_color_list(tbl.get("trail_color", "white"), max(1, len(trail)),
                                f"{where}.trail_color"),
    )


def _ground(tbl, where):
    _keys(tbl, GROUND_KEYS, where)
    color = _color(tbl.get("color", "white"), f"{where}.color")
    colors = _char_map(tbl.get("colors", {}), f"{where}.colors", True)
    blink = _char_map(tbl.get("blink", {}), f"{where}.blink", False)
    fps = _num(tbl.get("fps", 2.0), f"{where}.fps", lo=0)
    raw_tiles = tbl.get("tile", [])
    if not isinstance(raw_tiles, list) or not raw_tiles:
        raise ThemeError(f"{where}: needs at least one [[ground.tile]]")
    tiles = []
    for i, t in enumerate(raw_tiles):
        tw = f"{where}.tile[{i}]"
        _keys(t, ART_KEYS, tw)
        tiles.append(_art(t, tw, color=color, colors=colors, blink=blink, fps=fps))
    lights = None
    if "lights" in tbl:
        lw = f"{where}.lights"
        lt = tbl["lights"]
        _keys(lt, LIGHT_KEYS, lw)
        if "on" not in lt or "off" not in lt:
            raise ThemeError(f"{lw}: needs both 'on' and 'off' characters")
        lights = Lights(
            on=_char(lt["on"], f"{lw}.on", allow_space=False),
            off=_char(lt["off"], f"{lw}.off", allow_space=False),
            on_color=_color(lt.get("on_color", "yellow bold"), f"{lw}.on_color"),
            off_color=_color(lt.get("off_color", color + " dim"), f"{lw}.off_color"),
            ratio=_num(lt.get("ratio", 0.35), f"{lw}.ratio", lo=0, hi=1),
            rate=_num(lt.get("rate", 3.0), f"{lw}.rate", lo=0),
        )
    gap = _range(tbl.get("gap", [0, 2]), f"{where}.gap", lo=0)
    return Ground(
        tiles=tuple(tiles),
        height=_num(tbl.get("height", 0.35), f"{where}.height", lo=0.05, hi=1),
        gap=(int(gap[0]), int(gap[1])),
        floor=_char(tbl["floor"], f"{where}.floor") if "floor" in tbl else None,
        floor_color=_color(tbl.get("floor_color", color), f"{where}.floor_color"),
        lights=lights,
    )


def _sky(tbl, where):
    _keys(tbl, SKY_KEYS, where)
    chars = tbl.get("chars", [" ", ".", "+", "*"])
    if not isinstance(chars, list) or not chars:
        raise ThemeError(f"{where}.chars: expected a non-empty list of characters")
    chars = tuple(_char(c, f"{where}.chars") for c in chars)
    return Sky(
        chars=chars,
        colors=_color_list(tbl.get("colors", "white"), len(chars), f"{where}.colors"),
        density=_num(tbl.get("density", 0.03), f"{where}.density", lo=0, hi=1),
        speed=_range(tbl.get("speed", [0.5, 3.0]), f"{where}.speed", lo=0),
    )


def parse(data, name="theme", source=None):
    _keys(data, TOP_KEYS, "theme")
    actors = data.get("actor", [])
    if not isinstance(actors, list):
        raise ThemeError("actor: use [[actor]] blocks")
    background = data.get("background")
    if background is not None:
        _color(background, "background")
    return Theme(
        name=str(data.get("name", name)),
        description=str(data.get("description", "")),
        background=background,
        sky=_sky(data["sky"], "sky") if "sky" in data else None,
        ground=_ground(data["ground"], "ground") if "ground" in data else None,
        actors=tuple(_actor(a, f"actor[{i}] ({a.get('name', '?') if isinstance(a, dict) else '?'})")
                     for i, a in enumerate(actors)),
        source=source,
    )


# ---------- finding and loading ----------

def builtin_dir():
    return Path(__file__).parent / "themes"


def user_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "termscape" / "themes"


def available():
    """Theme name -> file. User themes override built-ins with the same file name."""
    found = {}
    for d in (builtin_dir(), user_dir()):
        if d.is_dir():
            for p in sorted(d.glob("*.toml")):
                found[p.stem] = p
    return found


def resolve(name_or_path):
    """Turn a theme name, 'random', or a path to a .toml file into a file path."""
    p = Path(name_or_path).expanduser()
    if p.suffix == ".toml" or os.sep in name_or_path:
        if not p.is_file():
            raise ThemeError(f"theme file not found: {p}")
        return p.resolve()
    themes = available()
    if name_or_path == "random":
        return random.choice(list(themes.values()))
    if name_or_path not in themes:
        raise ThemeError(f"unknown theme {name_or_path!r}; available: {', '.join(themes)}")
    return themes[name_or_path]


def load(path):
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ThemeError(f"{path}: TOML syntax error: {e}") from None
    except OSError as e:
        raise ThemeError(f"{path}: {e.strerror}") from None
    try:
        return parse(data, name=path.stem, source=path)
    except ThemeError as e:
        raise ThemeError(f"{path}: {e}") from None
