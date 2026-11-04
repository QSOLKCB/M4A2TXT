"""Exercise real GTK widgets under Xvfb; the recognizer is a controlled fixture."""
import argparse
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scribe.core import Cancelled, Result
from scribe.desktop import BatchController, PROFILES, Settings
from scribe.gui import Adw, Gdk, Gio, GLib, Gtk, ScribeApplication
from scribe.setup_progress import SetupLog


def spin(until=lambda: False, seconds=.3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        if until():
            return
        time.sleep(.01)
    if until.__name__ != "<lambda>" and not until():
        raise AssertionError("GTK operation timed out")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    if not Gtk.init_check():
        raise SystemExit("A real display is required; run under xvfb-run.")
    Adw.init()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        output = root / "Transcripts"
        output.mkdir()
        calls = []
        def recognizer(source, options, cancel, event):
            calls.append((source.name, options.device, options.model.name))
            if source.name == "Slow.m4a":
                event("Transcribing locally — CPU…")
                if cancel.wait(5):
                    raise Cancelled()
                raise AssertionError("Expected cancellation")
            event("Whisper: 50%")
            target = output / (source.stem + ".txt")
            target.write_text("Welcome to this deep dive. Today we're looking at how local transcription works.\n", encoding="utf-8")
            return Result(target, "GPU (CUDA0)" if options.device == "gpu" else "CPU", .1, "fixture", False)
        controller = BatchController(recognizer)
        settings = Settings(root / "settings.json", output)
        app = ScribeApplication(controller=controller, settings=settings, root=root)
        app.register(None)
        app.activate()
        win = app.window
        assert win is not None
        spin()

        def screenshot(name):
            if args.screenshots:
                args.screenshots.mkdir(parents=True, exist_ok=True)
                spin(seconds=.4)
                width = max(window.get_surface().get_width() for window in Gtk.Window.get_toplevels() if window.get_visible())
                height = max(window.get_surface().get_height() for window in Gtk.Window.get_toplevels() if window.get_visible())
                subprocess.run(["import", "-window", "root", "-crop", f"{width}x{height}+0+0",
                                "+repage", str(args.screenshots / name)], check=True)

        assert list(win.profile_buttons) == ["laptop", "mid", "high"]
        assert list(win.device_buttons) == ["cpu", "gpu"]
        assert settings.device == "cpu"
        assert win.primary_button.get_label() == "Set up CPU"
        screenshot("01-empty-setup.png")
        win.task_row.set_selected(1)
        win.language_row.set_text("fr")
        win.format_row.set_selected(2)
        win.large_text_row.set_active(True)
        assert win.profile.model == "small"
        assert settings.task == "translate" and settings.output_format == "vtt"
        assert Settings(settings.path).large_text
        win.profile_buttons["mid"].set_active(True)
        assert win.profile.model == "small"  # Turbo must never handle translation.
        win.task_row.set_selected(0)
        win.language_row.set_text("en")
        win.format_row.set_selected(0)
        win.large_text_row.set_active(False)
        win.profile_buttons["laptop"].set_active(True)

        # Keep fixture setup running while checking actual widgets at each stage.
        # No network, compiler, or model is involved in these UI checks.
        real_setup = controller.setup
        def exercise_setup(profile_key, device, outcome="complete"):
            updates = queue.Queue()
            def installer(profile, cancel, event, root, selected_device):
                while not cancel.wait(.01):
                    try:
                        value = updates.get_nowait()
                    except queue.Empty:
                        continue
                    if value == "complete":
                        return
                    if value == "fail":
                        raise ValueError("Fixture setup failure")
                    event(value)
                raise Cancelled()
            win.profile_buttons[profile_key].set_active(True)
            win.device_buttons[device].set_active(True)
            with mock.patch.object(controller, "setup", side_effect=lambda profile, root, device:
                                   real_setup(profile, root, installer, device)):
                win.primary_button.emit("clicked")
            assert controller.busy
            assert win.progress.get_visible()
            assert win.progress.get_show_text()
            assert win.setup_spinner.get_spinning()
            assert win.log_hint.get_label() == "See Details For Log"
            assert win.progress_value is None
            engine = "CUDA" if device == "gpu" else "CPU"
            updates.put(f"Building {engine} engine: 76%")
            spin(lambda: win.progress.get_text() == "76%", seconds=3)
            assert win.progress.get_fraction() == .76
            assert "76%" in win.status.get_text()
            assert "elapsed" in win.elapsed.get_text()
            updates.put(SetupLog("compiler output while progress stays at 76%"))
            spin()
            assert win.progress.get_fraction() == .76
            if profile_key == "high" and device == "gpu" and outcome == "complete":
                screenshot("05-setup-cuda-progress.png")
                win.set_default_size(540, 600)
                screenshot("06-compact-setup-progress.png")
                win.set_default_size(850, 740)
            details = win.show_details()
            buffer = win.detail_buffers[-1]
            updates.put(SetupLog("live setup diagnostic"))
            spin(lambda: "live setup diagnostic" in buffer.get_text(*buffer.get_bounds(), True), seconds=3)
            assert "live setup diagnostic" in buffer.get_text(*buffer.get_bounds(), True)
            details.close()
            spin()
            assert not win.detail_buffers
            updates.put("Downloading model: 50% (1.0 MiB / 2.0 MiB)")
            spin(lambda: win.progress.get_text() == "50%", seconds=3)
            assert win.progress.get_fraction() == .5
            updates.put("Downloading model: 1.5 MiB received")
            spin(lambda: win.status.get_text() == "Downloading model: 1.5 MiB received", seconds=3)
            assert win.progress_value is None
            assert win.progress.get_text() == "Working…"
            updates.put("Verifying model…")
            spin(lambda: win.status.get_text() == "Verifying model…", seconds=3)
            assert win.progress_value is None
            assert win.progress.get_text() == "Working…"
            if outcome == "cancel":
                win.cancel_button.emit("clicked")
            else:
                updates.put(outcome)
            spin(lambda: not controller.busy, seconds=3)
            assert not controller.busy
            assert not win.progress_row.get_visible()
            assert not win.setup_spinner.get_spinning()
            assert win.progress.get_fraction() == 0
            assert win.progress_value is None
            expected = {"complete": "Setup complete", "cancel": "Setup cancelled", "fail": "Setup failed"}
            assert expected[outcome] in win.status.get_text()

        for key in PROFILES:
            for device in ("cpu", "gpu"):
                exercise_setup(key, device)
        exercise_setup("high", "gpu", "cancel")
        exercise_setup("high", "gpu", "fail")
        win.device_buttons["cpu"].set_active(True)
        for profile in PROFILES.values():
            options = profile.options(output, root)
            options.model.parent.mkdir(exist_ok=True)
            options.model.write_bytes(b"test model; fake recognizer")
        engine = root / ".runtime/cpu/bin/whisper-cli"
        engine.parent.mkdir(parents=True)
        engine.write_text("test fixture")
        engine.chmod(0o755)
        for key in ("high", "laptop", "mid"):
            win.profile_buttons[key].set_active(True)
            spin()
            assert settings.profile == key
            assert sum(choice.get_active() for choice in win.profile_buttons.values()) == 1
        assert settings.profile == "mid"
        assert "CPU" in win.mode_note.get_text()
        assert not win.primary_button.get_sensitive()
        win.device_buttons["gpu"].set_active(True)
        spin()
        assert settings.device == "gpu"
        assert sum(choice.get_active() for choice in win.device_buttons.values()) == 1
        assert win.primary_button.get_label() == "Set up GPU"
        gpu = root / ".runtime/cuda/bin/whisper-cli"
        gpu.parent.mkdir(parents=True)
        gpu.write_text("CUDA fixture; no hardware inference")
        gpu.chmod(0o755)
        win.refresh()
        source = root / "Deep Dive — Episode 01.m4a"
        source.write_bytes(b"fixture")
        filelist = Gdk.FileList.new_from_list([Gio.File.new_for_path(str(source))])
        assert win.drop_target.emit("drop", filelist, 0., 0.)
        assert len(controller.jobs) == 1
        assert win.primary_button.get_sensitive()
        screenshot("02-ready-mid.png")
        win.primary_button.emit("clicked")
        assert not win.progress.get_show_text()  # Existing transcription display.
        assert not win.setup_spinner.get_visible()
        spin(lambda: not controller.busy, seconds=5)
        assert controller.jobs[0].status == "Saved"
        assert not win.primary_button.get_sensitive()
        assert calls == [(source.name, "gpu", "ggml-large-v3-turbo-q5_0.bin")]
        assert "GPU (CUDA0)" in win.rows[controller.jobs[0].id][0].get_subtitle()
        transcript = win.show_transcript(controller.jobs[0])
        assert transcript is not None
        screenshot("03-transcript.png")
        transcript.close()
        spin()
        details = win.show_details()
        spin()
        details.close()
        spin()
        # Changing quality preserves the explicit processor selection.
        win.profile_buttons["high"].set_active(True)
        assert settings.device == "gpu"
        high = root / "High GPU.m4a"
        high.write_bytes(b"fixture")
        win.add_paths([high])
        win.primary_button.emit("clicked")
        spin(lambda: not controller.busy, seconds=5)
        assert calls[-1] == (high.name, "gpu", "ggml-large-v3.bin")
        assert len(calls) == 2
        win.device_buttons["cpu"].set_active(True)
        spin()
        assert settings.profile == "high"
        assert settings.device == "cpu"
        assert Settings(settings.path).device == "cpu"
        # Native async dialogs must handle cancellation without changing the queue.
        win.choose_audio()
        spin()
        for dialog in list(Gtk.Window.get_toplevels()):
            if dialog is not win and dialog.get_visible():
                dialog.close()
        spin()
        assert len(controller.jobs) == 2
        win.set_default_size(540, 600)
        screenshot("04-compact.png")
        # Closing during work must request cancellation and reap the worker.
        slow = root / "Slow.m4a"
        slow.write_bytes(b"fixture")
        win.add_paths([slow])
        win.primary_button.emit("clicked")
        spin(lambda: any(call[0] == slow.name for call in calls), seconds=2)
        assert controller.busy
        assert calls[-1] == (slow.name, "cpu", "ggml-large-v3.bin")
        assert all(not choice.get_sensitive() for choice in win.device_buttons.values())
        win.close()
        spin(lambda: not controller.busy and win.poll_id is None, seconds=5)
        assert not controller.busy
        assert controller.jobs[0].result.output.is_file()
        assert not (output / "Slow.txt").exists()
        assert controller.jobs[2].status == "Cancelled"
        app.quit()
        print("GTK smoke PASS: all six setup combinations, build/model progress, live logs, setup completion/failure/cancellation, presets, CPU/GPU selection, Mid/High GPU routing, file drop, queue, completion, preview, dialogs, cancellation, close. Setup and recognizer are fixtures; no downloads or hardware inference.")


if __name__ == "__main__":
    main()
