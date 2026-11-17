"""Color specs ("yellow bold", "208 dim", "bright_cyan") and their curses attributes."""

BASIC = {
    "black": 0, "red": 1, "green": 2, "yellow": 3,
    "blue": 4, "magenta": 5, "cyan": 6, "white": 7,
}
ATTR_NAMES = ("bold", "dim", "reverse", "underline", "italic")


class ColorError(ValueError):
    pass


def parse_color(spec):
    """Parse a color spec into (fg, attrs).

    fg is None for the terminal's default color, or 0-255. attrs is a tuple of
    names from ATTR_NAMES. Words are space-separated; the last color word wins.
    """
    if not isinstance(spec, str):
        raise ColorError(f"color must be a string, got {spec!r}")
    fg = None
    attrs = []
    for word in spec.lower().split():
        if word in ATTR_NAMES:
            attrs.append(word)
        elif word == "default":
            fg = None
        elif word in BASIC:
            fg = BASIC[word]
        elif word.startswith("bright_") and word[7:] in BASIC:
            fg = BASIC[word[7:]] + 8
        elif word.isdigit() and int(word) <= 255:
            fg = int(word)
        else:
            raise ColorError(
                f"unknown color word {word!r}; use a name (red, bright_cyan, ...), "
                f"a number 0-255, 'default', or one of {', '.join(ATTR_NAMES)}")
    return fg, tuple(attrs)


def to_basic(n):
    """Approximate a 256-color index with one of the 8 basic colors -> (index, bold)."""
    if n < 8:
        return n, False
    if n < 16:
        return n - 8, True
    if n >= 232:  # grayscale ramp
        level = (n - 232) / 23
        return (7, level > 0.7) if level > 0.25 else (0, True)
    n -= 16
    r, g, b = n // 36, (n // 6) % 6, n % 6
    top = max(r, g, b)
    if top == 0:
        return 0, False
    # Keep every channel close to the strongest one; red=1, green=2, blue=4 matches curses order.
    idx = (r >= top - 1 and r > 0) | ((g >= top - 1 and g > 0) << 1) | ((b >= top - 1 and b > 0) << 2)
    return idx, top >= 4


class CursesPalette:
    """Turns color specs into curses attributes, allocating color pairs on demand."""

    def __init__(self, background=None):
        import curses
        self.curses = curses
        curses.start_color()
        try:
            curses.use_default_colors()
            self.default_ok = True
        except curses.error:
            self.default_ok = False
        self.set_background(background)

    def set_background(self, background):
        self.pairs = {}
        self.cache = {}
        self.next_pair = 1
        fg = parse_color(background)[0] if background else None
        self.bg = self._fg(fg)[0] if fg is not None else (-1 if self.default_ok else 0)

    def _fg(self, fg):
        c = self.curses
        if fg is None:
            return (-1 if self.default_ok else 7), 0
        if fg < 8 or (fg < 16 and c.COLORS >= 16) or c.COLORS >= 256:
            return fg, 0
        idx, bold = to_basic(fg)
        return idx, (c.A_BOLD if bold else 0)

    def _pair(self, fg):
        key = (fg, self.bg)
        if key not in self.pairs:
            if self.next_pair >= self.curses.COLOR_PAIRS:
                return 0
            self.curses.init_pair(self.next_pair, fg, self.bg)
            self.pairs[key] = self.next_pair
            self.next_pair += 1
        return self.pairs[key]

    def attr(self, spec):
        if spec not in self.cache:
            c = self.curses
            fg, names = parse_color(spec)
            fg, extra = self._fg(fg)
            value = c.color_pair(self._pair(fg)) | extra
            for name in names:
                value |= getattr(c, "A_" + name.upper(), 0)
            self.cache[spec] = value
        return self.cache[spec]

    def background_attr(self):
        return self.curses.color_pair(self._pair(self._fg(None)[0]))
