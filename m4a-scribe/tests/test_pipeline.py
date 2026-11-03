"""Real FFmpeg integration plus a controlled fake recognizer.

These tests validate orchestration, not Whisper recognition quality.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from scribe.core import Cancelled, Options, ScribeError, publish_text, run_process, transcribe

TEXT = " Uh, no—no, that's what I said.\nTwo plus two is five. Café.\n"


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "output"
        self.out.mkdir()
        self.model = self.root / "test model.bin"
        self.model.write_bytes(b"fake model for adapter tests only")
        self.input = self.root / "audio ; $(touch INJECTED) ' café.m4a"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=0.25", "-c:a", "aac", str(self.input)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.cpu = self.make_engine("cpu", """
assert '--no-gpu' in sys.argv
assert '--translate' not in sys.argv
assert '--prompt' not in sys.argv
assert '--no-fallback' in sys.argv
assert '--vad' not in sys.argv
with wave.open(sys.argv[sys.argv.index('--file')+1], 'rb') as w:
    assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
out = pathlib.Path(sys.argv[sys.argv.index('--output-file')+1] + '.txt')
out.write_bytes(TEXT.encode('utf-8'))
""")
        self.options = Options(self.model, self.out, device="cpu", cpu_engine=self.cpu)

    def make_engine(self, name, body):
        path = self.root / name
        path.write_text(f"#!{sys.executable}\nimport sys, pathlib, wave, time\nTEXT = {TEXT!r}\n" + body)
        path.chmod(0o700)
        return path

    def test_real_m4a_decode_preserves_recognizer_bytes_and_input(self):
        original = self.input.read_bytes()
        result = transcribe(self.input, self.options)
        self.assertEqual(result.output.read_bytes(), TEXT.encode("utf-8"))
        self.assertEqual(result.source_sha256, hashlib.sha256(original).hexdigest())
        self.assertEqual(self.input.read_bytes(), original)
        self.assertEqual(result.device, "CPU")
        self.assertFalse((self.root / "INJECTED").exists())

    def test_existing_output_and_symlink_are_never_overwritten(self):
        existing = self.out / (self.input.stem + ".txt")
        victim = self.root / "existing.txt"
        victim.write_text("keep this")
        existing.symlink_to(victim)
        result = transcribe(self.input, self.options)
        self.assertEqual(victim.read_text(), "keep this")
        self.assertTrue(existing.is_symlink())
        self.assertIn("(2)", result.output.name)

    def test_parallel_publication_is_no_clobber(self):
        text = self.root / "text"
        text.write_text(TEXT)
        paths, errors = [], []
        def run():
            try:
                paths.append(publish_text(text, self.out, "same", threading.Event()))
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=run) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(paths)), 8)
        self.assertTrue(all(path.read_text() == TEXT for path in paths))
        self.assertEqual(list(self.out.glob("*.partial")), [])

    def test_long_unicode_output_name_is_bounded(self):
        text = self.root / "text"
        text.write_text(TEXT)
        result = publish_text(text, self.out, "é" * 125, threading.Event())
        self.assertLess(len(result.name.encode("utf-8")), 255)
        self.assertEqual(result.read_text(), TEXT)

    def test_pre_cancel_does_not_start_work(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            transcribe(self.input, self.options, cancel)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_output_publication_error_keeps_existing_files(self):
        text = self.root / "text"
        text.write_text(TEXT)
        keep = self.out / "keep.txt"
        keep.write_text("original")
        with mock.patch("scribe.core.os.link", side_effect=OSError("unsupported")):
            with self.assertRaises(ScribeError):
                publish_text(text, self.out, "new", threading.Event())
        self.assertEqual(list(self.out.iterdir()), [keep])
        self.assertEqual(keep.read_text(), "original")

    def test_corrupt_m4a_leaves_no_transcript(self):
        self.input.write_bytes(b"not audio")
        with self.assertRaises(ScribeError):
            transcribe(self.input, self.options)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_empty_audio_rejected(self):
        self.input.write_bytes(b"")
        with self.assertRaisesRegex(ScribeError, "empty"):
            transcribe(self.input, self.options)

    def test_fifo_does_not_block(self):
        fifo = self.root / "pipe.m4a"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ScribeError, "regular"):
            transcribe(fifo, self.options)

    def test_source_symlink_rejected(self):
        link = self.root / "link.m4a"
        link.symlink_to(self.input)
        with self.assertRaises(ScribeError):
            transcribe(link, self.options)

    def test_gpu_failure_retries_whole_job_once_on_cpu(self):
        gpu = self.make_engine("gpu", "raise SystemExit(9)\n")
        options = Options(self.model, self.out, device="auto", cpu_engine=self.cpu, gpu_engine=gpu)
        events = []
        result = transcribe(self.input, options, event=events.append)
        self.assertEqual(result.device, "CPU fallback")
        self.assertTrue(any("retrying" in message for message in events))
        self.assertEqual(result.output.read_text(), TEXT)

    def test_explicit_gpu_does_not_retry_cpu(self):
        gpu = self.make_engine("gpu", "raise SystemExit(9)\n")
        options = Options(self.model, self.out, device="gpu", cpu_engine=self.cpu, gpu_engine=gpu)
        with self.assertRaisesRegex(ScribeError, "exit 9"):
            transcribe(self.input, options)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_cuda_backend_is_confirmed_across_chunks_and_long_logs(self):
        gpu = self.make_engine("gpu", """
assert '--no-gpu' not in sys.argv
assert '--no-prints' not in sys.argv
print('whisper_backend_init_gpu: using CU', end='', flush=True)
time.sleep(.15)
print('DA0 backend', flush=True)
print('diagnostic filler\\n' * 8000, flush=True)
pathlib.Path(sys.argv[sys.argv.index('--output-file')+1] + '.txt').write_text(TEXT)
""")
        events = []
        result = transcribe(self.input, Options(self.model, self.out, device="gpu", gpu_engine=gpu), event=events.append)
        self.assertEqual(result.device, "GPU (CUDA0)")
        self.assertEqual(result.output.read_text(), TEXT)
        self.assertIn("CUDA backend confirmed: CUDA0.", events)

    def test_cuda_build_flag_without_backend_does_not_publish(self):
        gpu = self.make_engine("gpu", """
print('system_info: CUDA = 1')
pathlib.Path(sys.argv[sys.argv.index('--output-file')+1] + '.txt').write_text(TEXT)
""")
        with self.assertRaisesRegex(ScribeError, "did not report an active CUDA backend"):
            transcribe(self.input, Options(self.model, self.out, device="gpu", gpu_engine=gpu))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_cuda_init_failure_after_selection_does_not_publish(self):
        gpu = self.make_engine("gpu", """
print('whisper_backend_init_gpu: using CUDA0 backend')
print('whisper_backend_init_gpu: failed to initialize CUDA0 backend')
pathlib.Path(sys.argv[sys.argv.index('--output-file')+1] + '.txt').write_text(TEXT)
""")
        with self.assertRaisesRegex(ScribeError, "could not initialize"):
            transcribe(self.input, Options(self.model, self.out, device="gpu", gpu_engine=gpu))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_missing_gpu_stops_process_before_silent_cpu_work(self):
        gpu = self.make_engine("gpu", "print('whisper_backend_init_gpu: no GPU found', flush=True)\ntime.sleep(30)\n")
        start = time.monotonic()
        with self.assertRaisesRegex(ScribeError, "No CPU retry was started"):
            transcribe(self.input, Options(self.model, self.out, device="gpu", gpu_engine=gpu))
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_auto_retries_if_cuda_process_silently_used_cpu(self):
        gpu = self.make_engine("gpu", "print('whisper_backend_init_gpu: no GPU found')\n")
        result = transcribe(self.input, Options(self.model, self.out, device="auto", cpu_engine=self.cpu, gpu_engine=gpu))
        self.assertEqual(result.device, "CPU fallback")
        self.assertEqual(result.output.read_text(), TEXT)

    def test_cancel_during_inference_publishes_nothing(self):
        engine = self.make_engine("slow", "time.sleep(30)\n")
        cancel = threading.Event()
        errors = []
        options = Options(self.model, self.out, device="cpu", cpu_engine=engine)
        started = threading.Event()
        def run():
            try:
                transcribe(self.input, options, cancel,
                           lambda msg: started.set() if "Transcribing" in msg else None)
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(started.wait(5))
        cancel.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(errors[0], Cancelled)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_missing_engine_and_no_model_do_not_download(self):
        options = Options(self.model, self.out, device="cpu", cpu_engine=self.root / "missing")
        with self.assertRaisesRegex(ScribeError, "missing"):
            transcribe(self.input, options)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_decoded_limit_rejects_instead_of_silently_truncating(self):
        long = self.root / "long.m4a"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=2", "-c:a", "aac", str(long)], check=True)
        options = Options(self.model, self.out, device="cpu", cpu_engine=self.cpu, max_seconds=1)
        with self.assertRaisesRegex(ScribeError, "exceeds"):
            transcribe(long, options)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_empty_recognizer_output_is_explicit(self):
        empty = self.make_engine("empty", "pathlib.Path(sys.argv[sys.argv.index('--output-file')+1] + '.txt').write_bytes(b'')\n")
        result = transcribe(self.input, Options(self.model, self.out, device="cpu", cpu_engine=empty))
        self.assertTrue(result.empty)
        self.assertEqual(result.output.read_bytes(), b"")

    def test_success_without_output_is_failure(self):
        empty = self.make_engine("no-output", "raise SystemExit(0)\n")
        with self.assertRaisesRegex(ScribeError, "without producing"):
            transcribe(self.input, Options(self.model, self.out, device="cpu", cpu_engine=empty))

    def test_audio_decode_cannot_request_http(self):
        calls = []
        from scribe import core
        real = core.run_process
        def capture(argv, *args):
            calls.append(argv)
            return real(argv, *args)
        with mock.patch.object(core, "run_process", side_effect=capture):
            transcribe(self.input, self.options)
        decode = calls[0]
        self.assertEqual(decode[decode.index("-protocol_whitelist") + 1], "file,pipe")
        self.assertEqual(decode[decode.index("-f") + 1], "mov")


class ProcessTests(unittest.TestCase):
    def test_cancellation_terminates_started_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            started = work / "pid"
            cancel = threading.Event()
            errors = []
            def run():
                try:
                    run_process([sys.executable, "-c",
                        "import os,time,pathlib; pathlib.Path('pid').write_text(str(os.getpid())); time.sleep(30)"],
                        work, cancel, lambda _: None, "fixture")
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=run)
            worker.start()
            deadline = time.monotonic() + 5
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(started.exists())
            pid = int(started.read_text())
            cancel.set()
            worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertIsInstance(errors[0], Cancelled)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)


if __name__ == "__main__":
    unittest.main()
