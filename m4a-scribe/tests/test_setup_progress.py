"""Setup progress uses real output, without GPU builds or model downloads."""
import contextlib
import hashlib
import importlib.util
import io
import itertools
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

from scribe.core import Cancelled, run_process
from scribe.desktop import BatchController, PROFILES, setup_profile
from scribe.setup_progress import SetupLog, SetupOutput, setup_fraction


class SetupProgressTests(unittest.TestCase):
    def test_build_chunks_parallel_percentages_and_stage_changes(self):
        events = []
        progress = SetupOutput(events.append, "CUDA")
        for chunk in (b"Setup: Configuring CUDA engine...\n[ 7", b"6%] Building CUDA\r",
                      b"compiler warning\n[ 74%] Built target\n[ 76%] duplicate\n",
                      b"\x1b[32m[100%] Built target\x1b[0m\nSetup: Checking CUDA engine..."):
            progress.feed(chunk)
        progress.finish()
        messages = [item for item in events if isinstance(item, str)]
        self.assertEqual(messages, ["Configuring CUDA engine...", "Building CUDA engine: 76%",
                                    "Building CUDA engine: 100%", "Checking CUDA engine..."])
        self.assertEqual(setup_fraction(messages[1]), .76)
        self.assertIsNone(setup_fraction(messages[-1]))
        self.assertIn(SetupLog("compiler warning"), events)

    def test_ninja_progress_and_unrelated_percentages(self):
        events = []
        progress = SetupOutput(events.append, "CPU")
        progress.feed(b"Receiving objects: 80%\n[3/4] Building CXX\n[2/4] late\n[0/0] invalid\n[101%] invalid\n")
        self.assertEqual([item for item in events if isinstance(item, str)], ["Building CPU engine: 75%"])
        self.assertIsNone(setup_fraction("Downloading model: 20.0 MiB received"))
        self.assertEqual(setup_fraction("Downloading model: 50% (1.0 MiB / 2.0 MiB)"), .5)

    def test_real_process_reports_progress_before_exit_even_with_a_long_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            cancel = threading.Event()
            messages = []
            def update(value):
                if isinstance(value, str):
                    messages.append(value)
                    if value == "Building CUDA engine: 76%":
                        cancel.set()
            progress = SetupOutput(update, "CUDA")
            with self.assertRaises(Cancelled):
                run_process([sys.executable, "-c",
                    "import sys,time; print('[ 76%] Building CUDA', flush=True); "
                    "print('diagnostic\\n' * 2000, flush=True); time.sleep(30)"],
                    work, cancel, lambda _: None, "Engine setup", observer=progress.feed)
            self.assertIn("Building CUDA engine: 76%", messages)

    def test_every_preset_and_processor_streams_engine_and_model_progress(self):
        for profile, device in itertools.product(PROFILES.values(), ("cpu", "gpu")):
            with self.subTest(profile=profile.key, device=device), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                mode = "cuda" if device == "gpu" else "cpu"
                messages = []
                def process(argv, work, cancel, event, label, observer=None):
                    self.assertIsNotNone(observer)
                    if label == "Engine setup":
                        self.assertEqual(argv[-1], mode)
                        observer(b"[ 76%] Building engine\n")
                        target = root / f".runtime/{mode}/bin/whisper-cli"
                        target.parent.mkdir(parents=True)
                        target.write_text("fixture")
                        target.chmod(0o755)
                    else:
                        self.assertIn(profile.model, argv)
                        observer(b"Setup: Downloading model: 50% (1.0 MiB / 2.0 MiB)\n")
                        observer(b"Setup: Verifying model...\n")
                        target = root / f"models/ggml-{profile.model}.bin"
                        target.parent.mkdir()
                        target.write_bytes(b"fixture")
                with mock.patch("scribe.desktop.shutil.which", return_value="fixture"), \
                        mock.patch("scribe.desktop.run_process", side_effect=process):
                    setup_profile(profile, threading.Event(), messages.append, root, device)
                self.assertIn(f"Building {mode.upper()} engine: 76%", messages)
                self.assertIn("Downloading model: 50% (1.0 MiB / 2.0 MiB)", messages)
                self.assertIn("Verifying model...", messages)

    def test_diagnostics_do_not_replace_progress_and_failure_is_not_completion(self):
        controller = BatchController()
        def installer(profile, cancel, event, root, device):
            event("Building CPU engine: 76%")
            event(SetupLog("compiler warning"))
            raise ValueError("fixture failure")
        controller.setup(PROFILES["laptop"], installer=installer)
        controller.thread.join(3)
        self.assertFalse(controller.thread.is_alive())
        events = controller.drain()
        self.assertIn(("log", "compiler warning"), events)
        self.assertIn("compiler warning", controller.logs)
        self.assertEqual(controller.summary, "Setup failed. Open Details for the reason.")
        self.assertFalse(controller.busy)


class ModelProgressTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "scripts/install-model.py"
        spec = importlib.util.spec_from_file_location("model_installer", path)
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)
        original_models = self.installer.MODELS.copy()
        self.addCleanup(lambda: self.installer.MODELS.update(original_models))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = b"controlled model bytes"

    def download(self, model="large-v3", length=None, valid=True):
        class Response(io.BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 4))
        response = Response(self.data)
        response.headers = {} if length is None else {"Content-Length": length}
        digest = hashlib.sha1(self.data).hexdigest() if valid else "0" * 40
        self.installer.MODELS[model] = digest
        output = io.StringIO()
        directory = self.root / model
        with mock.patch.object(sys, "argv", ["install-model.py", model, "--download", "--directory", str(directory)]), \
                mock.patch.object(self.installer.urllib.request, "urlopen", return_value=response), \
                mock.patch.object(self.installer.time, "monotonic", side_effect=itertools.count(step=.3)), \
                contextlib.redirect_stdout(output):
            if valid:
                self.assertEqual(self.installer.main(), 0)
            else:
                with self.assertRaisesRegex(ValueError, "integrity check failed"):
                    self.installer.main()
        return directory, output.getvalue()

    def test_all_models_show_download_progress_then_verification(self):
        for model in self.installer.MODELS:
            with self.subTest(model=model):
                directory, log = self.download(model, str(len(self.data)))
                self.assertIn("Downloading model: 0%", log)
                self.assertIn("Downloading model: 54%", log)
                self.assertLess(log.index("Downloading model: 100%"), log.index("Verifying model"))
                target = directory / f"ggml-{model}.bin"
                self.assertEqual(target.read_bytes(), self.data)
                self.assertTrue(target.with_suffix(".bin.sha256").exists())

    def test_missing_or_invalid_length_shows_bytes_without_fake_percentage(self):
        for length in (None, "garbage", "0", "-1", str(5 * 1024**3)):
            with self.subTest(length=length):
                directory, log = self.download(length=length)
                self.assertIn("Downloading model: 12.0 B received", log)
                self.assertNotIn("%", log)
                for file in directory.iterdir():
                    file.unlink()

    def test_download_completion_is_not_installation_success_on_bad_checksum(self):
        directory, log = self.download(length=str(len(self.data)), valid=False)
        self.assertIn("Downloading model: 100%", log)
        self.assertIn("Verifying model", log)
        self.assertNotIn("Installed:", log)
        self.assertEqual(list(directory.iterdir()), [])

    def test_existing_model_verifies_without_network_or_download_progress(self):
        directory, _ = self.download(length=str(len(self.data)))
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["install-model.py", "large-v3", "--download", "--directory", str(directory)]), \
                mock.patch.object(self.installer.urllib.request, "urlopen") as fetch, \
                contextlib.redirect_stdout(output):
            self.installer.main()
        fetch.assert_not_called()
        self.assertIn("Verifying installed model", output.getvalue())
        self.assertNotIn("Downloading model:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
