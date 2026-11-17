"""Scene simulation and drawing.

The engine only talks to two small interfaces, so it can run without a real terminal:
  canvas.size() -> (height, width)      canvas.put(y, x, ch, attr)
  palette.attr(color_spec) -> int
"""

import math
import random
from collections import deque

from .text import char_width

# Screens shorter than this are "strip" sized: smaller ground limit, gentler streaks,
# and actors marked only = "strip" are used instead of only = "full".
COMPACT_BELOW = 12

BLINK_HZ = 1.5


class CompiledArt:
    """Art with transparency resolved and colors turned into attributes.

    Each row's leading and trailing spaces are transparent; spaces between the
    first and last visible character are drawn, so shapes stay solid.
    """

    def __init__(self, art, palette, color=None):
        base = color or art.color
        self.width, self.height, self.fps = art.width, art.height, art.fps
        self.frames = []
        for rows in art.frames:
            cells = []
            for dy, row in enumerate(rows):
                visible = row.strip(" ")
                if not visible:
                    continue
                dx = len(row) - len(row.lstrip(" "))
                for ch in visible:
                    w = char_width(ch)
                    if w == 0:
                        continue
                    attr = palette.attr(art.colors.get(ch, base))
                    alt = art.blink.get(ch)
                    alt_attr = palette.attr(art.colors.get(alt, base)) if alt else attr
                    cells.append((dy, dx, ch, attr, alt, alt_attr))
                    dx += w
            self.frames.append(cells)

    def draw(self, canvas, x, y, age, blink_on):
        frames = self.frames
        cells = frames[int(age * self.fps) % len(frames)] if len(frames) > 1 else frames[0]
        for dy, dx, ch, attr, alt, alt_attr in cells:
            if alt and blink_on:
                canvas.put(y + dy, x + dx, alt, alt_attr)
            else:
                canvas.put(y + dy, x + dx, ch, attr)


class Item:
    """One live actor on screen."""

    __slots__ = ("spec", "art", "x", "y", "vx", "vy", "ay", "age", "phase", "dir", "life", "trail")


class Scene:
    def __init__(self, canvas, palette, theme):
        self.canvas = canvas
        self.palette = palette
        self.set_theme(theme)

    def set_theme(self, theme):
        self.theme = theme
        self._compiled = {}
        self.reset()

    # ---------- building ----------

    def reset(self):
        self.h, self.w = self.canvas.size()
        self.compact = self.h < COMPACT_BELOW
        self.t = 0.0
        self.items = []
        self.specs = [a for a in self.theme.actors
                      if a.only == "any" or (a.only == "strip") == self.compact]
        self._trail_attrs = {id(s): [self.palette.attr(c) for c in s.trail_color]
                             for s in self.specs}
        self._build_sky()
        self._build_ground()
        for spec in self.specs:
            for _ in range(spec.start):
                self.spawn(spec, initial=True)

    def compiled(self, art, color=None):
        key = (id(art), color)
        if key not in self._compiled:
            self._compiled[key] = CompiledArt(art, self.palette, color)
        return self._compiled[key]

    def _build_sky(self):
        sky = self.theme.sky
        self.stars = []
        if not sky or self.w <= 0 or self.h <= 0:
            return
        self.sky_attrs = [self.palette.attr(c) for c in sky.colors]
        count = int(self.w * self.h * sky.density)
        self.stars = [(random.randrange(self.w), random.randrange(self.h),
                       random.uniform(0, math.tau), random.uniform(*sky.speed))
                      for _ in range(count)]

    def _build_ground(self):
        g = self.theme.ground
        self.tiles = []
        self.lights = []
        if not g:
            return
        limit = self.h - 2 if self.compact else int(self.h * g.height)
        fits = [t for t in g.tiles if t.height <= max(1, limit) and t.height < self.h]
        x = -random.randint(0, 3)
        while fits and x < self.w:
            art = random.choice(fits)
            comp = self.compiled(art)
            y = self.h - art.height
            self.tiles.append((x, y, comp, random.uniform(0, 10)))
            if g.lights:
                for dy, dx, ch, *_ in comp.frames[0]:
                    if ch in (g.lights.on, g.lights.off):
                        self.lights.append([x + dx, y + dy, random.random() < g.lights.ratio])
            x += art.width + random.randint(*g.gap)
        if g.lights:
            self.light_on = (g.lights.on, self.palette.attr(g.lights.on_color))
            self.light_off = (g.lights.off, self.palette.attr(g.lights.off_color))
        self.floor_attr = self.palette.attr(g.floor_color)

    # ---------- spawning ----------

    @staticmethod
    def _place(rng, total, size):
        """Pick a position in a [0..1] band, where 0 = top/left edge and 1 = bottom/right edge."""
        lo, hi = (min(max(v, 0.0), 1.0) for v in rng)
        return random.uniform(lo, hi) * max(0, total - size)

    def spawn(self, spec, initial=False):
        if spec.art.height > self.h:
            return
        if spec.direction == "left":
            d = -1
        elif spec.direction == "right":
            d = 1
        else:
            d = random.choice((-1, 1))
        art = spec.mirrored if d < 0 and spec.mirrored is not None else spec.art
        it = Item()
        it.spec = spec
        it.art = self.compiled(art, random.choice(spec.palette) if spec.palette else None)
        it.dir = d
        it.age = 0.0
        it.phase = random.uniform(0, math.tau)
        it.vx = it.vy = it.ay = 0.0
        it.life = 0.0
        it.trail = None
        W, H, aw, ah = self.w, self.h, art.width, art.height
        speed = random.uniform(*spec.speed)
        m = spec.motion
        if m == "drift":
            it.y = self._place(spec.y, H, ah)
            it.x = random.uniform(0, max(0, W - aw)) if initial else (-aw if d > 0 else W)
            it.vx = d * speed
        elif m == "static":
            it.x = self._place(spec.x, W, aw)
            it.y = self._place(spec.y, H, ah)
        elif m == "rise":
            it.x = self._place(spec.x, W, aw)
            it.y = random.uniform(0, H) if initial else H
            it.vy, it.ay = -speed, -spec.accel
        elif m == "fall":
            it.x = self._place(spec.x, W, aw)
            it.y = random.uniform(-ah, H) if initial else -ah
            it.vy, it.ay = speed, spec.accel
        else:  # streak
            x = random.uniform(*spec.x) * W
            it.x = x if d < 0 else W - x
            it.y = random.uniform(*spec.y) * H
            slope = random.uniform(*spec.slope) * (0.35 if self.compact else 1.0)
            it.vx, it.vy = d * speed, speed * slope
            it.life = random.uniform(*spec.life)
            it.trail = deque(maxlen=len(spec.trail) + 1)
        self.items.append(it)

    def random_event(self):
        moving = [s for s in self.specs if s.motion != "static"]
        if moving:
            self.spawn(random.choice(moving))

    # ---------- simulation ----------

    def update(self, dt):
        self.t += dt
        counts = {}
        for it in self.items:
            counts[id(it.spec)] = counts.get(id(it.spec), 0) + 1
        for spec in self.specs:
            if (spec.rate and random.random() < spec.rate * dt
                    and counts.get(id(spec), 0) < spec.max):
                self.spawn(spec)

        g = self.theme.ground
        if self.lights and g.lights.rate and random.random() < g.lights.rate * dt:
            light = random.choice(self.lights)
            light[2] = not light[2]

        for it in self.items:
            self._step(it, dt)
        self.items = [it for it in self.items if self._alive(it)]

    def _step(self, it, dt):
        it.age += dt
        if it.trail is None:
            it.vy += it.ay * dt
            it.x += it.vx * dt
            it.y += it.vy * dt
            return
        it.life -= dt
        if it.life > 0:
            it.x += it.vx * dt
            it.y += it.vy * dt
            pos = (math.floor(it.x), math.floor(it.y))
            if not it.trail or it.trail[-1] != pos:
                it.trail.append(pos)
            if it.y > self.h + 1 or (it.dir < 0 and it.x < -1) or (it.dir > 0 and it.x > self.w + 1):
                it.life = 0.0
        elif it.trail:
            it.trail.popleft()  # once spent, the tail catches up with the head

    def _alive(self, it):
        m = it.spec.motion
        if m == "drift":
            return it.x < self.w + 1 if it.dir > 0 else it.x + it.art.width > -1
        if m == "rise":
            return it.y + it.art.height > -1
        if m == "fall":
            return it.y < self.h + 1
        if m == "streak":
            return it.life > 0 or bool(it.trail)
        return True

    # ---------- drawing ----------

    def draw(self):
        blink_on = int(self.t * BLINK_HZ) % 2 == 1
        self._draw_sky()
        for it in self.items:
            if it.spec.layer == "back":
                self._draw_item(it, blink_on)
        self._draw_ground(blink_on)
        for it in self.items:
            if it.spec.layer == "front":
                self._draw_item(it, blink_on)

    def _draw_sky(self):
        sky = self.theme.sky
        if not self.stars:
            return
        n = len(sky.chars)
        put = self.canvas.put
        for x, y, phase, speed in self.stars:
            i = min(int((math.sin(self.t * speed + phase) + 1) / 2 * n), n - 1)
            ch = sky.chars[i]
            if ch != " ":
                put(y, x, ch, self.sky_attrs[i])

    def _draw_ground(self, blink_on):
        g = self.theme.ground
        if not g:
            return
        if g.floor:
            for x in range(self.w):
                self.canvas.put(self.h - 1, x, g.floor, self.floor_attr)
        for x, y, comp, phase in self.tiles:
            comp.draw(self.canvas, x, y, self.t + phase, blink_on)
        for x, y, on in self.lights:
            ch, attr = self.light_on if on else self.light_off
            self.canvas.put(y, x, ch, attr)

    def _draw_item(self, it, blink_on):
        spec = it.spec
        if it.trail is not None:
            attrs = self._trail_attrs[id(spec)]
            n = len(it.trail)
            head = it.life > 0
            for i, (x, y) in enumerate(it.trail):
                k = n - 1 - i - (1 if head else 0)  # 0 = just behind the head
                if k < 0:
                    it.art.draw(self.canvas, x, y, it.age, blink_on)
                else:
                    k = min(k, len(spec.trail) - 1)
                    self.canvas.put(y, x, spec.trail[k], attrs[k])
            return
        x, y = it.x, it.y
        if spec.sway:
            x += math.sin(it.age * 1.5 + it.phase) * spec.sway
        if spec.bob:
            y += math.sin(it.age * 2.0 + it.phase) * spec.bob
        it.art.draw(self.canvas, round(x), round(y), it.age, blink_on)
