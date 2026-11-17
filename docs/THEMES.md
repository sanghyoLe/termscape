# Writing themes

A theme is one TOML file. Put it in `~/.config/termscape/themes/<name>.toml`
(or `$XDG_CONFIG_HOME/termscape/themes/`) and it shows up in `termscape themes`;
a user theme with the same name as a built-in one replaces it. You can also run
any file directly:

```sh
termscape --theme ./aquarium.toml          # full screen
termscape strip --theme ./aquarium.toml    # as a strip
termscape check ./aquarium.toml            # validate and report mistakes
```

Themes are data only: no code runs when a theme is loaded, so sharing them is safe.
The built-in themes in [`src/termscape/themes/`](../src/termscape/themes/) are good
starting points.

A scene has three layers, drawn back to front:

1. **`[sky]`**: characters that twinkle in place (stars, plankton, fireflies)
2. **`[ground]`**: tiles lined up along the bottom (buildings, reef, trees)
3. **`[[actor]]`**: things that move (fish, clouds, meteors, snow). Each actor
   has a `layer`, `"back"` (behind the ground) or `"front"`.

## Minimal theme

```toml
name = "pond"

[[actor]]
art = "><>"
palette = ["yellow", "cyan", "magenta"]
```

## Art

Art is a string; use TOML's `'''` literal strings for multi-line art so
backslashes and quotes need no escaping. The newline right after the opening
`'''` is ignored.

```toml
art = '''
 __
\/ o\
/\__/
'''
```

- **Transparency:** spaces before the first and after the last visible character
  of each row are transparent. Spaces in between are drawn, so shapes stay solid.
- **Animation:** use `frames = ['''...''', '''...''']` instead of `art`, plus `fps`.
- **Direction:** draw art facing **right**. Drifting actors are mirrored
  automatically when they move left (`( ) < > [ ] { } / \` are swapped). Set
  `mirror = false` for symmetric art or art that should not flip.
- Tabs are not allowed. Unicode is fine; wide (CJK/emoji) characters take two cells.

## Colors

A color is a string of words: one color plus any of `bold dim reverse underline italic`.

| Form | Example |
|---|---|
| name | `red` `green` `yellow` `blue` `magenta` `cyan` `white` `black` |
| bright name | `bright_red`, `bright_cyan`, ... |
| 256-color number | `208` (orange), `94` (brown); approximated on 8-color terminals |
| terminal default | `default` |

Any art (actor or tile) takes:

| Key | Meaning | Default |
|---|---|---|
| `color` | color for the whole art | `"white"` |
| `colors` | per-character colors, e.g. `{ "o" = "white bold", "^" = "red" }` | `{}` |
| `blink` | characters that alternate ~1.5×/s, e.g. `{ "*" = "+" }` | `{}` |
| `fps` | frames per second when `frames` has more than one entry | `2` |

The top-level `background = "17"` paints the whole screen; leave it out to keep
your terminal's own background (including transparency).

## `[sky]`

Each sky cell cycles smoothly through `chars`, dim to bright and back. A `" "`
entry makes the cell disappear for part of the cycle.

| Key | Meaning | Default |
|---|---|---|
| `chars` | list of characters from dimmest to brightest | `[" ", ".", "+", "*"]` |
| `colors` | one color, or one per entry in `chars` | `"white"` |
| `density` | fraction of screen cells that get a sky character | `0.03` |
| `speed` | twinkle speed range | `[0.5, 3.0]` |

## `[ground]` and `[[ground.tile]]`

Tiles are placed left to right along the bottom, picked at random among those
that fit. In the strip (screens under 12 rows) tiles may be up to *height − 2*
rows; on full screens up to `height` × screen height. Include some 1–3 row tiles
so the strip has a ground too.

| Key | Meaning | Default |
|---|---|---|
| `height` | max ground height as a fraction of the screen (full screen) | `0.35` |
| `gap` | random gap between tiles, `[min, max]` columns | `[0, 2]` |
| `floor` | a character repeated along the bottom row | none |
| `floor_color` | its color | ground `color` |
| `color`, `colors`, `blink`, `fps` | defaults for every tile | |
| `lights` | windows that switch on and off, see below | none |

Each `[[ground.tile]]` has `art` or `frames` and may override `color`, `colors`,
`blink` and `fps`.

**Lights:** every `on` or `off` character inside a tile becomes a light that
starts on with probability `ratio` and flips at random, about `rate` times per second.

```toml
lights = { on = "#", off = ".", on_color = "yellow bold", off_color = "blue dim", ratio = 0.35, rate = 3 }
```

## `[[actor]]`

| Key | Meaning | Default |
|---|---|---|
| `name` | label shown in error messages | `"actor"` |
| `motion` | `drift`, `rise`, `fall`, `streak` or `static` | `drift` |
| `speed` | cells per second, a number or `[min, max]` | depends on motion |
| `rate` | chance per second of a new one appearing | `0.1` (`static`: 0) |
| `max` | most on screen at once (automatic spawns only) | `3` |
| `start` | how many are placed when the scene starts | `0` (`static`: 1) |
| `x`, `y` | where it appears, see below | depends on motion |
| `layer` | `back` (behind ground) or `front` | `front` |
| `only` | `any`, `full` (screens of 12+ rows) or `strip` | `any` |
| `palette` | list of colors; each new actor picks one (overrides `color`) | none |
| `bob` | vertical wobble in rows | `0` |
| `sway` | horizontal wobble in columns (`fall`, `rise`) | `0` |
| `accel` | acceleration in cells/s² (`rise` and `fall`) | `0` |
| `direction` | `random`, `left` or `right` (`drift`, `streak`) | `random` (`streak`: `left`) |
| `mirror` | flip art when drifting left | `true` |

`x` and `y` are a number or `[min, max]` between 0 and 1, where 0 puts the art at
the left/top edge and 1 at the right/bottom edge (the art always fits on screen).

### Motions

- **`drift`**: enters from the left or right edge and crosses the screen at a
  height picked from `y`. Clouds, fish, UFOs, birds.
- **`rise`**: starts below the screen at a column from `x` and moves up.
  Bubbles, rockets (`layer = "back"` makes it launch from behind the ground).
- **`fall`**: starts above the screen and falls. Snow, rain, leaves; add `sway`.
- **`static`**: placed once at `x`, `y`. Moons, signs. Use `start` for how many.
- **`streak`**: a head with a fading trail that shoots diagonally, then the trail
  catches up and it disappears. Meteors. Extra keys:

| Key | Meaning | Default |
|---|---|---|
| `trail` | characters from just behind the head to the tail end | `["=", "=", "-", "-", "-", "-", "."]` |
| `trail_color` | one color or one per trail character | `"white"` |
| `slope` | rows dropped per column moved | `[0.2, 0.4]` |
| `life` | seconds before it starts fading | `[0.6, 1.6]` |

For a streak, `x` and `y` are fractions of the screen for the starting point
(`x` may exceed 1 to start off-screen).

## Full screen and strip

The same theme runs full-screen and as a 3–8 row strip. Big art simply never
appears where it does not fit, but a scene usually looks better with a small
version of its main pieces. Pair them with `only`:

```toml
[[actor]]
name = "moon"
motion = "static"
only = "full"
art = '''
 _..._
:::::::
`:::::'
'''

[[actor]]
name = "moon-small"
motion = "static"
only = "strip"
art = "(@)"
```
