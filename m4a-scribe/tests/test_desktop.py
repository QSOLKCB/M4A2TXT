"""Desktop behaviour without a display, downloads, or model weights."""
import importlib.util
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from scribe.core import Cancelled, Options, Result, ScribeError
from scribe.desktop import BatchController, PROFILES, Settings, readiness, setup_profile


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.calls = []
        self.controller = BatchController(self.recognise)
        self.options = Options(self.root / "model.bin", self.output)

    def audio(self, name):
        path = self.root / name
        path.write_bytes(b"fixture; recognition is controlled by this test")
        return path

    def recognise(self, source, options, cancel, event):
        self.calls.append(source.name)
        out = options.output_dir / (source.stem + ".txt")
        out.write_text(" Uh, no. Two plus two is five.\n", encoding="utf-8")
        return Result(out, "CPU", .1, "fixture", False)

    def finish(self):
        deadline = time.monotonic() + 5
        while self.controller.busy and time.monotonic() < deadline:
            self.controller.drain()
            time.sleep(.01)
        self.controller.drain()
        self.assertFalse(self.controller.busy)

    def test_new_batch_skips_already_completed_files(self):
        a, b = self.audio("a.m4a"), self.audio("b.m4a")
        self.controller.add([a, a])
        self.controller.start(self.options)
        self.finish()
        self.controller.add([a, b])
        self.controller.start(self.options)
        self.finish()
        self.assertEqual(self.calls, ["a.m4a", "b.m4a"])
        self.assertEqual(len(self.controller.jobs), 2)
        with self.assertRaises(ScribeError):
            self.controller.start(self.options)

    def test_failure_keeps_other_results_and_retries_only_failed_file(self):
        a, b = self.audio("a.m4a"), self.audio("b.m4a")
        def flaky(source, *args):
            if source == a:
                raise ScribeError("fixture failure")
            return self.recognise(source, *args)
        self.controller.runner = flaky
        self.controller.add([a, b])
        self.controller.start(self.options)
        self.finish()
        self.assertEqual([job.status for job in self.controller.jobs], ["Failed", "Saved"])
        self.controller.runner = self.recognise
        self.controller.start(self.options)
        self.finish()
        self.assertEqual(self.calls, ["b.m4a", "a.m4a"])

    def test_cancellation_preserves_completed_result_and_stops_queue(self):
        entered = threading.Event()
        def runner(source, options, cancel, event):
            if source.name == "b.m4a":
                entered.set()
                if cancel.wait(3):
                    raise Cancelled()
                raise AssertionError("Cancellation was not delivered")
            return self.recognise(source, options, cancel, event)
        self.controller.runner = runner
        self.controller.add([self.audio(name) for name in ("a.m4a", "b.m4a", "c.m4a")])
        self.controller.start(self.options)
        self.assertTrue(entered.wait(2))
        self.controller.clear()
        self.controller.remove(self.controller.jobs[0].id)
        self.assertEqual(len(self.controller.jobs), 3)
        self.controller.stop()
        self.finish()
        self.assertEqual([j.status for j in self.controller.jobs], ["Saved", "Cancelled", "Not started"])
        self.assertEqual(self.calls, ["a.m4a"])
        self.assertTrue((self.output / "a.txt").is_file())

    def test_add_rejects_symlinks_and_non_audio_files(self):
        path = self.audio("a.m4a")
        link = self.root / "link.m4a"
        link.symlink_to(path)
        errors = self.controller.add([link, self.audio("notes.txt"), path])
        self.assertEqual(len(errors), 2)
        self.assertEqual([j.source for j in self.controller.jobs], [path])

    def test_settings_recover_from_malformed_and_preserve_output(self):
        path = self.root / "settings.json"
        path.write_text("not json")
        settings = Settings(path, self.output)
        self.assertEqual(settings.profile, "laptop")
        settings.profile = "mid"
        settings.save()
        loaded = Settings(path)
        self.assertEqual((loaded.profile, loaded.output), ("mid", self.output))
        self.assertEqual(set(__import__('json').loads(path.read_text())), {"profile", "output"})

    def test_profile_models_are_supported_by_explicit_installer(self):
        path = Path(__file__).resolve().parents[1] / "scripts/install-model.py"
        spec = importlib.util.spec_from_file_location("model_installer", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for profile in PROFILES.values():
            self.assertIn(profile.model, module.MODELS)
            options = profile.options(self.output, self.root)
            self.assertTrue(options.model.is_relative_to(self.root / "models"))
        self.assertEqual(PROFILES["laptop"].device, "cpu")
        self.assertTrue(all(PROFILES[key].device == "auto" for key in ("mid", "high")))

    def test_readiness_is_for_selected_profile_not_any_model(self):
        options = PROFILES["laptop"].options(self.output, self.root)
        options.cpu_engine.parent.mkdir(parents=True)
        options.cpu_engine.write_text("fixture")
        options.cpu_engine.chmod(0o755)
        options.model.parent.mkdir()
        options.model.write_bytes(b"fixture")
        with mock.patch("scribe.desktop.shutil.which", return_value="/usr/bin/ffmpeg"):
            self.assertEqual(readiness(PROFILES["laptop"], self.root), [])
            self.assertEqual(readiness(PROFILES["mid"], self.root), ["model download"])

    def test_setup_requires_explicit_start_and_never_runs_recognizer(self):
        calls = []
        def installer(profile, cancel, event, root):
            calls.append(profile.key)
            event("Fixture setup complete")
        self.controller.add([self.audio("a.m4a")])
        self.assertEqual(calls, [])
        self.controller.setup(PROFILES["mid"], self.root, installer)
        self.finish()
        self.assertEqual(calls, ["mid"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.controller.jobs[0].status, "Ready")

    def test_setup_gpu_failure_keeps_cpu_and_downloads_selected_model(self):
        commands, messages = [], []
        def run(argv, work, cancel, event, label):
            commands.append(argv)
            if label == "GPU setup":
                raise ScribeError("no supported GPU")
            if label == "Engine setup":
                engine = self.root / ".runtime/cpu/bin/whisper-cli"
                engine.parent.mkdir(parents=True)
                engine.write_text("fixture")
                engine.chmod(0o755)
            if label == "Model setup":
                model = self.root / "models/ggml-large-v3-turbo-q5_0.bin"
                model.parent.mkdir()
                model.write_bytes(b"fixture")
        with mock.patch("scribe.desktop.run_process", side_effect=run), mock.patch("scribe.desktop.shutil.which", return_value="/fixture/tool"):
            setup_profile(PROFILES["mid"], threading.Event(), messages.append, self.root)
        self.assertEqual(len(commands), 3)
        self.assertIn("--download", commands[-1])
        self.assertIn("large-v3-turbo-q5_0", commands[-1])
        self.assertTrue(any("CPU engine remains" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
