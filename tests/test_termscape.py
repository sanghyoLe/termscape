"""Run with: python3 -m unittest discover -s tests   (from the repository root)"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from termscape import theme as themes  # noqa: E402
from termscape.colors import ColorError, parse_color, to_basic  # noqa: E402
from termscape.engine import Scene  # noqa: E402


class FakeCanvas:
    def __init__(self, h, w):
        self.h, self.w = h, w
        self.cells = {}

    def size(self):
        return self.h, self.w

    def put(self, y, x, ch, attr=0):
        assert isinstance(ch, str) and len(ch) == 1, ch
        if 0 <= y < self.h and 0 <= x < self.w:
            self.cells[(y, x)] = ch


class FakePalette:
    def attr(self, spec):
        parse_color(spec)
        return 0


def simulate(theme, h, w, seconds=30, dt=0.05):
    canvas = FakeCanvas(h, w)
    scene = Scene(canvas, FakePalette(), theme)
    for i in range(int(seconds / dt)):
        canvas.cells.clear()
        scene.update(dt)
        if i % 40 == 0:
            scene.random_event()
        scene.draw()
    return scene, canvas


def toml(text):
    import tomllib
    return themes.parse(tomllib.loads(text))


class BuiltinThemes(unittest.TestCase):
    def test_all_builtin_themes_load(self):
        found = themes.available()
        for name in ("night", "ocean", "forest", "snow"):
            self.assertIn(name, found)
        for path in found.values():
            with self.subTest(theme=path.stem):
                t = themes.load(path)
                self.assertTrue(t.actors)

    def test_all_builtin_themes_run_at_many_sizes(self):
        random.seed(1)
        for path in themes.available().values():
            t = themes.load(path)
            for h, w in ((40, 120), (24, 80), (5, 100), (3, 40), (1, 10), (12, 30)):
                with self.subTest(theme=t.name, size=(h, w)):
                    scene, canvas = simulate(t, h, w, seconds=10)
                    if h >= 5:
                        self.assertTrue(canvas.cells, "nothing was drawn")

    def test_strip_and_full_actor_selection(self):
        t = themes.load(themes.resolve("night"))
        strip = Scene(FakeCanvas(5, 100), FakePalette(), t)
        full = Scene(FakeCanvas(40, 120), FakePalette(), t)
        self.assertIn("moon-small", [s.name for s in strip.specs])
        self.assertNotIn("moon", [s.name for s in strip.specs])
        self.assertIn("moon", [s.name for s in full.specs])

    def test_ground_fits_strip(self):
        t = themes.load(themes.resolve("night"))
        scene = Scene(FakeCanvas(5, 100), FakePalette(), t)
        self.assertTrue(scene.tiles)
        for x, y, comp, _ in scene.tiles:
            self.assertGreaterEqual(y, 2)


class ThemeValidation(unittest.TestCase):
    def assertThemeError(self, text, fragment):
        with self.assertRaises(themes.ThemeError) as cm:
            toml(text)
        self.assertIn(fragment, str(cm.exception))

    def test_minimal_theme(self):
        t = toml('[[actor]]\nart = "><>"\n')
        self.assertEqual(t.actors[0].motion, "drift")
        self.assertEqual(t.actors[0].mirrored.frames[0][0], "<><")

    def test_unknown_key_is_reported(self):
        self.assertThemeError('[[actor]]\nart = "x"\nsped = 3\n', "sped")

    def test_bad_color(self):
        self.assertThemeError('[[actor]]\nart = "x"\ncolor = "purple"\n', "purple")

    def test_bad_motion(self):
        self.assertThemeError('[[actor]]\nart = "x"\nmotion = "fly"\n', "motion")

    def test_art_and_frames_are_exclusive(self):
        self.assertThemeError('[[actor]]\nart = "x"\nframes = ["y"]\n', "exactly one")

    def test_tabs_rejected(self):
        self.assertThemeError('[[actor]]\nart = "a\\tb"\n', "tabs")

    def test_range_order(self):
        self.assertThemeError('[[actor]]\nart = "x"\nspeed = [5, 1]\n', "larger")

    def test_ground_needs_tiles(self):
        self.assertThemeError('[ground]\ncolor = "blue"\n', "ground.tile")

    def test_mirror_swaps_color_keys(self):
        t = toml('[[actor]]\nart = "(>"\ncolors = { ">" = "red" }\n')
        self.assertEqual(t.actors[0].mirrored.colors, {"<": "red"})

    def test_frames_padded_to_same_size(self):
        t = toml("[[actor]]\nframes = ['''\nab\n''', '''\na\nbcd\n''']\n")
        art = t.actors[0].art
        self.assertEqual((art.width, art.height), (3, 2))
        self.assertTrue(all(len(r) == 3 for f in art.frames for r in f))

    def test_resolve_unknown(self):
        with self.assertRaises(themes.ThemeError):
            themes.resolve("does-not-exist")


class Colors(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_color("yellow bold"), (3, ("bold",)))
        self.assertEqual(parse_color("bright_cyan"), (14, ()))
        self.assertEqual(parse_color("208 dim"), (208, ("dim",)))
        self.assertEqual(parse_color("default"), (None, ()))
        with self.assertRaises(ColorError):
            parse_color("256")

    def test_to_basic(self):
        self.assertEqual(to_basic(196)[0], 1)  # pure red
        self.assertEqual(to_basic(46)[0], 2)   # pure green
        self.assertEqual(to_basic(21)[0], 4)   # pure blue
        self.assertEqual(to_basic(226)[0], 3)  # yellow


class Transparency(unittest.TestCase):
    def test_outer_spaces_transparent_inner_spaces_opaque(self):
        t = toml("[[actor]]\nmotion = 'static'\nx = 0\ny = 0\nart = '  (  )  '\n")
        canvas = FakeCanvas(3, 20)
        scene = Scene(canvas, FakePalette(), t)
        scene.draw()
        row = [canvas.cells.get((0, x)) for x in range(8)]
        self.assertEqual(row, [None, None, "(", " ", " ", ")", None, None])


if __name__ == "__main__":
    unittest.main()
