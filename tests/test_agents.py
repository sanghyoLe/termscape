"""Events, pet and agent hooks. Run with: python3 -m unittest discover -s tests"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from termscape import events, hooks  # noqa: E402
from termscape.pet import Pet  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_termscape import FakeCanvas, FakePalette  # noqa: E402


class TempHome(unittest.TestCase):
    """Points every config/state location at a temporary directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        env = {
            "XDG_STATE_HOME": str(self.root / "state"),
            "CLAUDE_CONFIG_DIR": str(self.root / "claude"),
            "CODEX_HOME": str(self.root / "codex"),
            "TMUX": "", "TMUX_PANE": "",
        }
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def logged(self):
        path = events.log_path()
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


class Events(TempHome):
    def test_reader_follows_and_filters_by_window(self):
        events.emit("old", source="x")
        reader = events.Reader("srv:@1")
        self.assertEqual([e["event"] for e in reader.backlog], ["old"])
        with open(events.log_path(), "a") as f:
            for ev in ({"t": 1, "event": "mine", "window": "srv:@1"},
                       {"t": 1, "event": "other", "window": "srv:@2"},
                       {"t": 1, "event": "everyone"}):
                f.write(json.dumps(ev) + "\n")
            f.write('{"t": 1, "event": "half')  # not finished yet
        self.assertEqual([e["event"] for e in reader.poll()], ["mine", "everyone"])
        with open(events.log_path(), "a") as f:
            f.write('"}\n')
        self.assertEqual([e["event"] for e in reader.poll()], ["half"])

    def test_reader_follows_rotation(self):
        reader = events.Reader(None)
        events.emit("a")
        self.assertEqual(len(reader.poll()), 1)
        with mock.patch.object(events, "MAX_BYTES", 1):
            events.emit("b")  # same line length as "a", so only the inode reveals the rotation
        self.assertTrue(events.log_path().with_name("events.jsonl.old").exists())
        self.assertEqual([e["event"] for e in reader.poll()], ["b"])


class PetTest(unittest.TestCase):
    def test_grows_with_context_and_resets_on_new_session(self):
        pet = Pet()
        self.assertFalse(pet.alive)
        pet.apply({"t": 0, "event": "context", "source": "x"})  # alive, no data yet
        self.assertEqual(pet.current_stage()[1], "egg")
        for fraction, stage in ((0.1, "baby"), (0.3, "kid"), (0.5, "teen"), (0.8, "adult"), (0.95, "giant")):
            pet.apply({"t": 0, "event": "context", "source": "x", "session": "s1", "context": fraction})
            self.assertEqual(pet.current_stage()[1], stage)
        pet.apply({"t": 0, "event": "start", "source": "x", "session": "s2"})
        self.assertEqual(pet.current_stage()[1], "egg")

    def test_tokens_use_window_size(self):
        pet = Pet()
        pet.apply({"t": 0, "event": "done", "source": "codex", "tokens": 237500, "size": 475000})
        self.assertAlmostEqual(pet.fraction, 0.5)

    def test_tokens_beyond_default_window_assume_large_window(self):
        pet = Pet()
        pet.apply({"t": 0, "event": "done", "source": "claude", "tokens": 500_000})
        self.assertAlmostEqual(pet.fraction, 0.5)

    def test_moods(self):
        pet = Pet()
        pet.apply({"t": 100, "event": "done", "source": "x"})
        self.assertEqual(pet.mood(101), "happy")
        self.assertEqual(pet.mood(110), "idle")
        self.assertEqual(pet.mood(1000), "sleep")
        pet.apply({"t": 100, "event": "waiting", "source": "x"})
        self.assertEqual(pet.mood(5000), "waiting")

    def test_ignores_events_without_source(self):
        pet = Pet()
        pet.apply({"t": 0, "event": "working"})
        self.assertFalse(pet.alive)

    def test_draws_every_stage_and_mood_in_a_strip(self):
        for fraction in (None, 0.1, 0.3, 0.5, 0.8, 0.95):
            for event in ("working", "done", "waiting", "idle"):
                pet = Pet()
                pet.apply({"t": 0, "event": event, "source": "x", "context": fraction})
                for h, w in ((5, 80), (3, 40), (2, 20), (30, 100)):
                    canvas = FakeCanvas(h, w)
                    for i in range(30):
                        pet.draw(canvas, FakePalette(), h, w, 1.0 + i * 0.1, 0.1)
                    self.assertTrue(canvas.cells, (fraction, event, h, w))


def write_jsonl(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))


class Hooks(TempHome):
    def test_claude_tokens_skip_sidechains(self):
        t = self.root / "t.jsonl"
        write_jsonl(t, [
            {"type": "assistant", "message": {"usage": {"input_tokens": 1, "cache_creation_input_tokens": 2,
                                                        "cache_read_input_tokens": 3}}},
            {"type": "assistant", "isSidechain": True, "message": {"usage": {"input_tokens": 999}}},
            {"type": "user", "message": {"content": "hi"}},
        ])
        self.assertEqual(hooks.claude_tokens(t), 6)

    def test_codex_context(self):
        t = self.root / "r.jsonl"
        write_jsonl(t, [{"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 21831}, "model_context_window": 475000}}}])
        self.assertEqual(hooks.codex_context(t), (21831, 475000))

    def run_hook(self, agent, payload):
        hooks.handle_hook(agent, io.StringIO(json.dumps(payload)))
        return self.logged()

    def test_claude_hook_events(self):
        t = self.root / "t.jsonl"
        write_jsonl(t, [{"type": "assistant", "message": {"usage": {"input_tokens": 50000}}}])
        log = self.run_hook("claude", {"hook_event_name": "Stop", "session_id": "s", "transcript_path": str(t)})
        self.assertEqual((log[-1]["event"], log[-1]["tokens"], log[-1]["source"]), ("done", 50000, "claude"))
        self.run_hook("claude", {"hook_event_name": "Notification", "notification_type": "idle_prompt"})
        self.assertEqual(len(self.logged()), 1)  # idle prompts are ignored
        log = self.run_hook("claude", {"hook_event_name": "Notification", "notification_type": "permission_prompt"})
        self.assertEqual(log[-1]["event"], "waiting")
        log = self.run_hook("claude", {"hook_event_name": "SessionStart", "source": "compact"})
        self.assertEqual(log[-1]["event"], "compact")

    def test_codex_hook_finds_rollout_by_session(self):
        rollout = self.root / "codex" / "sessions" / "2026" / "11" / "11" / "rollout-x-abc123.jsonl"
        write_jsonl(rollout, [{"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 1000}, "model_context_window": 4000}}}])
        log = self.run_hook("codex", {"hook_event_name": "PermissionRequest", "session_id": "abc123"})
        self.assertEqual((log[-1]["event"], log[-1]["tokens"], log[-1]["size"]), ("waiting", 1000, 4000))

    def test_bad_payload_never_raises(self):
        self.assertEqual(hooks.handle_hook("claude", io.StringIO("not json")), 0)
        self.assertEqual(hooks.handle_hook("claude", io.StringIO('{"hook_event_name": "Stop", '
                                                                  '"transcript_path": "/nope"}')), 0)

    def test_connect_and_disconnect_claude_keep_other_settings(self):
        settings = hooks.claude_settings_path()
        settings.parent.mkdir(parents=True)
        original = {
            "theme": "dark",
            "statusLine": {"type": "command", "command": "my-status --fancy", "padding": 1},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]},
        }
        settings.write_text(json.dumps(original))
        with mock.patch("sys.stdout", io.StringIO()):
            hooks.connect("claude")
            hooks.connect("claude")  # running twice must not duplicate hooks
        data = json.loads(settings.read_text())
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(len(data["hooks"]["Stop"]), 2)
        self.assertIn("say done", json.dumps(data["hooks"]["Stop"]))
        self.assertIn("--wrap", data["statusLine"]["command"])
        self.assertEqual(data["statusLine"]["padding"], 1)
        self.assertTrue(data["hooks"]["PostToolUse"][0]["hooks"][0]["async"])
        with mock.patch("sys.stdout", io.StringIO()):
            hooks.disconnect("claude")
        self.assertEqual(json.loads(settings.read_text()), original)

    def test_connect_codex_creates_file_and_disconnect_cleans_up(self):
        with mock.patch("sys.stdout", io.StringIO()):
            hooks.connect("codex")
            data = json.loads(hooks.codex_hooks_path().read_text())
            self.assertEqual(set(data["hooks"]), set(hooks.CODEX_EVENT_MAP))
            hooks.disconnect("codex")
        self.assertEqual(json.loads(hooks.codex_hooks_path().read_text()), {})

    def test_statusline_emits_on_change_and_wraps(self):
        payload = json.dumps({"session_id": "s", "context_window": {
            "used_percentage": 42.4, "context_window_size": 200000}})
        for _ in range(2):
            with mock.patch("sys.stdin", io.StringIO(payload)), mock.patch("sys.stdout", io.StringIO()) as out:
                hooks.handle_statusline("echo hello")
        self.assertEqual(out.getvalue().strip(), "hello")
        log = self.logged()
        self.assertEqual(len(log), 1)  # unchanged percentage is not re-sent
        self.assertAlmostEqual(log[0]["context"], 0.424)


if __name__ == "__main__":
    unittest.main()
