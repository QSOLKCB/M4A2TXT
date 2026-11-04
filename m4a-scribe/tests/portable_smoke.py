"""Exercise the Tk desktop with a controlled worker and no model download."""
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from scribe.core import Result
from scribe.desktop import BatchController, Settings
from scribe.portable_gui import PortableWindow


def main():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        calls = []
        def recognize(source, options, cancel, event):
            calls.append(options)
            output = directory / 'result.srt'
            output.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello.\n', encoding='utf-8')
            return Result(output, 'CPU', .01, 'fixture', False)
        root = tk.Tk()
        controller = BatchController(recognize)
        settings = Settings(directory / 'settings.json', directory)
        window = PortableWindow(root, controller=controller, settings=settings)
        root.update()
        window.task.set('translate')
        window.language.set('fr')
        window.format.set('srt')
        window.profile.set('mid')
        assert window.effective_profile().model == 'small'
        source = directory / 'sample.m4a'
        source.write_bytes(b'controlled fixture')
        controller.add([source])
        window.needs_setup = lambda: []
        window.start()
        deadline = time.monotonic() + 5
        while controller.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        assert not controller.busy
        assert len(calls) == 1
        assert (calls[0].task, calls[0].language, calls[0].output_format) == ('translate', 'fr', 'srt')
        assert calls[0].model.name == 'ggml-small.bin'
        window.jobs.selection_set(str(controller.jobs[0].id))
        window.preview()
        root.update()
        assert any(isinstance(widget, tk.Toplevel) for widget in root.winfo_children())
        window.close()
        while time.monotonic() < deadline:
            try:
                root.update()
                if not root.winfo_exists():
                    break
            except tk.TclError:
                break
            time.sleep(.01)
    print('Tk smoke PASS: controls, compatible model selection, job options, output preview and close')


if __name__ == '__main__':
    main()
