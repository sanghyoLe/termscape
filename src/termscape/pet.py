"""A pet that lives in the scene and grows with your coding agent's context window.

It hatches when the first agent event arrives (see hooks.py), grows through six
stages as the context fills up, shrinks back in a puff of smoke when the context
is compacted or a new session starts, and shows what the agent is doing:

  working  wanders around, "..." bubble      waiting  "?" (the agent needs you)
  happy    jumps for a few seconds after a turn finishes
  sleep    "zZz" after a long idle           full     context >= 90%, "full!"
"""

import math

DEFAULT_WINDOW = 200_000

# (minimum context fraction, stage name, art, color). E = eyes, M = mouth.
STAGES = (
    (0.00, "egg", [" _ ", "(_)"], "white"),
    (0.05, "baby", [" .-. ", "(EME)"], "yellow bold"),
    (0.20, "kid", [" .--. ", "(E  E)", " `-M'"], "green bold"),
    (0.45, "teen", ["  .---.", " ( E E )", "  `-M-'"], "cyan bold"),
    (0.70, "adult", ["   .---.", "  / E E \\", " (   M   )", "  `-...-'"], "magenta bold"),
    (0.90, "giant", ["   .-------.", "  /  E   E  \\", " (     M     )", "  `-.......-'"], "red bold"),
)

# mood -> (eyes, mouth, speech bubble frames)
MOODS = {
    "idle": ("o", "-", None),
    "working": ("o", "o", (".", "..", "...")),
    "happy": ("^", "v", ("!", "!!")),
    "waiting": ("O", "o", ("?", " ")),
    "sleep": ("-", "_", ("z", "zZ", "zZz")),
    "full": ("x", "~", ("full!", "     ")),
}

PUFF = [" * . * ", "*  ~  *", " ' * ' "]

STATE_FOR_EVENT = {
    "start": "idle", "working": "working", "done": "happy", "waiting": "waiting",
    "idle": "idle", "compact": "working", "end": "sleep",
}

HAPPY_SECONDS = 6
SLEEP_AFTER = 300


class Pet:
    def __init__(self):
        self.alive = False
        self.session = None
        self.window_size = DEFAULT_WINDOW
        self.fraction = None
        self.exact_session = None
        self.state = "idle"
        self.state_t = 0.0
        self.stage = None
        self.puff_until = 0.0
        self.x = None
        self.dir = 1

    # ---------- events ----------

    def apply(self, ev, live=True):
        """Update from an event. `live` is False while replaying old events at startup."""
        if not ev.get("source"):
            return
        self.alive = True
        t = float(ev.get("t", 0))
        session = ev.get("session")
        if session and session != self.session:
            self.session = session
            self.fraction = None
        size = ev.get("size")
        if isinstance(size, (int, float)) and size > 0:
            self.window_size = size
        if isinstance(ev.get("context"), (int, float)):
            self.fraction = max(0.0, min(1.0, float(ev["context"])))
            self.exact_session = session  # exact numbers win over token estimates from now on
        elif isinstance(ev.get("tokens"), (int, float)) and (
                self.exact_session is None or self.exact_session != session):
            if ev["tokens"] > self.window_size:  # must be a larger-context model
                self.window_size = 1_000_000
            self.fraction = min(1.0, ev["tokens"] / self.window_size)
        if ev["event"] == "compact":
            self.fraction = None
        state = STATE_FOR_EVENT.get(ev["event"])
        if state:
            self.state, self.state_t = state, t

    def mood(self, now):
        state = self.state
        if state == "happy" and now - self.state_t > HAPPY_SECONDS:
            state = "idle"
        if state == "idle" and now - self.state_t > SLEEP_AFTER:
            state = "sleep"
        if state == "idle" and (self.fraction or 0) >= 0.9:
            state = "full"
        return state

    def current_stage(self):
        f = self.fraction if self.fraction is not None else 0.0
        chosen = STAGES[0]
        for stage in STAGES:
            if f >= stage[0]:
                chosen = stage
        return chosen

    # ---------- drawing ----------

    def draw(self, canvas, palette, h, w, now, dt):
        if not self.alive or h < 2:
            return
        stage = self.current_stage()
        if self.stage is not None and stage[1] != self.stage:
            self.puff_until = now + 1.0
        self.stage = stage[1]
        mood = self.mood(now)
        eyes, mouth, bubble = MOODS[mood]
        if mood == "idle" and now % 4 < 0.15:
            eyes = "-"  # blink

        rows = [r.replace("E", eyes).replace("M", mouth) for r in stage[2]]
        if len(rows) > h:
            rows = rows[-h:]
        width = max(len(r) for r in rows)
        home = int(w * 0.8) - width // 2
        if self.x is None or not (0 <= self.x <= max(0, w - width)):
            self.x = float(max(0, min(home, w - width)))
        if mood == "working":
            self.x += self.dir * 3.0 * dt
            if self.x > home + 8 or self.x > w - width:
                self.dir = -1
            elif self.x < home - 8 or self.x < 0:
                self.dir = 1
        x = round(self.x)
        y = h - len(rows)
        if mood == "happy":
            y -= round(abs(math.sin(now * 6)) * min(1, h - len(rows)))
        elif self.stage == "egg" and mood == "working":
            x += round(math.sin(now * 8) * 0.6)  # the egg wobbles

        if now < self.puff_until:
            rows = PUFF[-min(len(PUFF), h):]
            x -= (len(PUFF[0]) - width) // 2
            y = h - len(rows)
            attr = palette.attr("yellow bold")
            bubble = None
        else:
            attr = palette.attr(stage[3])

        for dy, row in enumerate(rows):
            visible = row.strip(" ")
            if not visible:
                continue
            dx = len(row) - len(row.lstrip(" "))
            for i, ch in enumerate(visible):
                canvas.put(y + dy, x + dx + i, ch, attr)

        if bubble:
            text = bubble[int(now * 2) % len(bubble)]
            by, bx = (y - 1, x + width) if y >= 1 else (y, x + width + 1)
            for i, ch in enumerate(text):
                if ch != " ":
                    canvas.put(by, bx + i, ch, palette.attr("yellow bold"))

        if self.fraction is not None:
            label = f"{round(self.fraction * 100)}%"
            for i, ch in enumerate(label):
                canvas.put(h - 1, x + width + 1 + i, ch, palette.attr("white dim"))
