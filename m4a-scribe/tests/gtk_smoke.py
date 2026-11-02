"""Exercise real GTK widgets under Xvfb; the recognizer is a controlled fixture."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scribe.core import Cancelled, Result
from scribe.desktop import BatchController, PROFILES, Settings
from scribe.gui import Adw, Gdk, Gio, GLib, Gtk, ScribeApplication


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
            calls.append(source.name)
            if source.name == "Slow.m4a":
                event("Transcribing locally — CPU…")
                if cancel.wait(5):
                    raise Cancelled()
                raise AssertionError("Expected cancellation")
            event("Whisper: 50%")
            target = output / (source.stem + ".txt")
            target.write_text("Welcome to this deep dive. Today we're looking at how local transcription works.\n", encoding="utf-8")
            return Result(target, "CPU", .1, "fixture", False)
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
                width = max(window.get_width() for window in Gtk.Window.get_toplevels() if window.get_visible())
                height = max(window.get_height() for window in Gtk.Window.get_toplevels() if window.get_visible())
                subprocess.run(["import", "-window", "root", "-crop", f"{width}x{height}+0+0",
                                "+repage", str(args.screenshots / name)], check=True)

        assert list(win.profile_buttons) == ["laptop", "mid", "high"]
        assert win.primary_button.get_label() == "Set up Laptop"
        screenshot("01-empty-setup.png")
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
        source = root / "Deep Dive — Episode 01.m4a"
        source.write_bytes(b"fixture")
        filelist = Gdk.FileList.new_from_list([Gio.File.new_for_path(str(source))])
        assert win.drop_target.emit("drop", filelist, 0., 0.)
        assert len(controller.jobs) == 1
        assert win.primary_button.get_sensitive()
        screenshot("02-ready-mid.png")
        win.primary_button.emit("clicked")
        spin(lambda: not controller.busy, seconds=5)
        assert controller.jobs[0].status == "Saved"
        assert not win.primary_button.get_sensitive()
        assert calls == [source.name]
        transcript = win.show_transcript(controller.jobs[0])
        assert transcript is not None
        screenshot("03-transcript.png")
        transcript.close()
        spin()
        details = win.show_details()
        spin()
        details.close()
        spin()
        # Native async dialogs must handle cancellation without changing the queue.
        win.choose_audio()
        spin()
        for dialog in list(Gtk.Window.get_toplevels()):
            if dialog is not win and dialog.get_visible():
                dialog.close()
        spin()
        assert len(controller.jobs) == 1
        win.set_default_size(540, 600)
        screenshot("04-compact.png")
        # Closing during work must request cancellation and reap the worker.
        slow = root / "Slow.m4a"
        slow.write_bytes(b"fixture")
        win.add_paths([slow])
        win.primary_button.emit("clicked")
        spin(lambda: slow.name in calls, seconds=2)
        assert controller.busy
        win.close()
        spin(lambda: not controller.busy and win.poll_id is None, seconds=5)
        assert not controller.busy
        assert controller.jobs[0].result.output.is_file()
        assert not (output / "Slow.txt").exists()
        assert controller.jobs[1].status == "Cancelled"
        app.quit()
        print("GTK smoke PASS: presets, setup state, file drop, queue, completion, preview, dialogs, cancellation, close.")


if __name__ == "__main__":
    main()
