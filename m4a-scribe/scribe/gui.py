"""Native desktop UI. Background work communicates through an in-process queue."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .core import Cancelled, Options, ROOT, ScribeError, transcribe


class App:
    def __init__(self, window: tk.Tk):
        self.window = window
        window.title("M4A Scribe")
        window.geometry("940x730")
        window.minsize(700, 560)
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.player: subprocess.Popen | None = None
        self.files: list[Path] = []
        self.results: dict[str, Path] = {}
        self.closing = False
        self.config_path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "m4a-scribe" / "settings.json"
        config = self.read_config()
        models = sorted((ROOT / "models").glob("ggml-*.bin"))
        default_model = next((p for p in models if p.name == "ggml-large-v3-turbo.bin"), models[0] if models else "")
        self.model = tk.StringVar(value=config.get("model", str(default_model)))
        self.output = tk.StringVar(value=config.get("output", str(Path.home() / "Documents" if (Path.home() / "Documents").exists() else Path.home())))
        self.device = tk.StringVar(value=config.get("device", "Auto"))
        self.language = tk.StringVar(value=config.get("language", "en"))
        self.status = tk.StringVar(value="Choose audio files to begin. Everything is processed on this computer.")

        style = ttk.Style()
        style.configure("Title.TLabel", font=("TkDefaultFont", 23, "bold"))
        style.configure("Sub.TLabel", foreground="#55616d")
        style.configure("Treeview", rowheight=29)
        frame = ttk.Frame(window, padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="M4A Scribe", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Audio in. Plain text out. All on your computer.", style="Sub.TLabel").pack(anchor="w", pady=(4, 18))

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(0, 8))
        self.add_button = ttk.Button(controls, text="Add audio files…", command=self.add)
        self.add_button.pack(side="left")
        self.clear_button = ttk.Button(controls, text="Clear queue", command=self.clear)
        self.clear_button.pack(side="left", padx=8)
        ttk.Button(controls, text="Play selected", command=self.play).pack(side="left")
        ttk.Button(controls, text="Stop audio", command=self.stop_audio).pack(side="left", padx=8)
        self.table = ttk.Treeview(frame, columns=("name", "status"), show="headings", height=6, selectmode="browse")
        self.table.heading("name", text="Audio file")
        self.table.heading("status", text="Status")
        self.table.column("name", width=520)
        self.table.column("status", width=190)
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.show_selected)

        settings = ttk.LabelFrame(frame, text="Transcription", padding=12)
        settings.pack(fill="x", pady=12)
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="Local model").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.model_entry = ttk.Entry(settings, textvariable=self.model)
        self.model_entry.grid(row=0, column=1, sticky="ew", pady=3)
        self.model_button = ttk.Button(settings, text="Choose…", command=self.choose_model)
        self.model_button.grid(row=0, column=2, padx=(8, 0))
        ttk.Label(settings, text="Save transcripts in").grid(row=1, column=0, sticky="w", padx=(0, 12))
        self.output_entry = ttk.Entry(settings, textvariable=self.output)
        self.output_entry.grid(row=1, column=1, sticky="ew", pady=3)
        self.output_button = ttk.Button(settings, text="Choose…", command=self.choose_output)
        self.output_button.grid(row=1, column=2, padx=(8, 0))
        more = ttk.Frame(settings)
        more.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Label(more, text="Processor").pack(side="left")
        self.device_box = ttk.Combobox(more, textvariable=self.device, values=("Auto", "GPU preferred", "CPU"), state="readonly", width=17)
        self.device_box.pack(side="left", padx=(8, 20))
        ttk.Label(more, text="Language").pack(side="left")
        self.language_entry = ttk.Entry(more, textvariable=self.language, width=8)
        self.language_entry.pack(side="left", padx=8)
        ttk.Label(more, text="en = English; auto = detect", style="Sub.TLabel").pack(side="left")
        self.setting_widgets = [self.model_entry, self.model_button, self.output_entry,
                                self.output_button, self.language_entry]

        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        self.start_button = ttk.Button(actions, text="Transcribe", command=self.start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Cancel batch", command=self.cancel_batch, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(actions, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(8, 0))
        ttk.Label(frame, textvariable=self.status, wraplength=850).pack(fill="x", pady=(10, 8))
        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill="both", expand=True)
        self.preview = self.text_tab("Transcript")
        self.log = self.text_tab("Details")
        ttk.Label(frame, text=f"{__version__} · Machine transcript: check important passages against the audio.", style="Sub.TLabel").pack(anchor="w", pady=(10, 0))
        self.window.after(100, self.poll)

    def text_tab(self, title):
        frame = ttk.Frame(self.tabs)
        self.tabs.add(frame, text=title)
        text = tk.Text(frame, height=9, wrap="word", padx=12, pady=10, state="disabled")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        return text

    def read_config(self):
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return {k: v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def write_config(self):
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.config_path.write_text(json.dumps({"model": self.model.get(), "output": self.output.get(),
                "device": self.device.get(), "language": self.language.get()}, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    def add(self):
        names = filedialog.askopenfilenames(title="Choose audio files", filetypes=[("Audio files", "*.m4a *.M4A *.mp4 *.mp3 *.wav *.flac *.aac *.ogg *.opus"), ("All files", "*")])
        for name in names:
            path = Path(name)
            if path not in self.files:
                row = str(len(self.files))
                self.files.append(path)
                self.table.insert("", "end", iid=row, values=(path.name, "Queued"))

    def clear(self):
        for row in self.table.get_children():
            self.table.delete(row)
        self.files.clear()
        self.results.clear()
        self.set_text(self.preview, "")

    def choose_model(self):
        name = filedialog.askopenfilename(title="Choose a local whisper.cpp GGML model", filetypes=[("Whisper model", "*.bin")])
        if name:
            self.model.set(name)

    def choose_output(self):
        name = filedialog.askdirectory(title="Choose transcript folder")
        if name:
            self.output.set(name)

    def set_text(self, widget, value, append=False):
        widget.configure(state="normal")
        if not append:
            widget.delete("1.0", "end")
        widget.insert("end", value)
        widget.see("end")
        widget.configure(state="disabled")

    def show_selected(self, _event=None):
        selection = self.table.selection()
        if selection and selection[0] in self.results:
            try:
                self.set_text(self.preview, self.results[selection[0]].read_text(encoding="utf-8"))
            except OSError as exc:
                self.status.set(str(exc))

    def play(self):
        selection = self.table.selection()
        if not selection:
            return
        ffplay = shutil.which("ffplay")
        if not ffplay:
            messagebox.showinfo("Playback", "Install FFmpeg with ffplay for local playback.")
            return
        self.stop_audio()
        try:
            self.player = subprocess.Popen([ffplay, "-nodisp", "-autoexit", "-loglevel", "error",
                "-protocol_whitelist", "file,pipe", "-i", str(self.files[int(selection[0])].absolute())],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            messagebox.showerror("Playback", str(exc))

    def stop_audio(self):
        if self.player:
            if self.player.poll() is None:
                self.player.terminate()
                try:
                    self.player.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    self.player.kill()
                    self.player.wait()
            self.player = None

    def start(self):
        if not self.files or (self.worker and self.worker.is_alive()):
            return
        if not self.model.get().strip():
            messagebox.showinfo("Choose a model", "Choose an installed whisper.cpp .bin model. The README explains one-time setup; the app never downloads models.")
            return
        self.write_config()
        options = Options(Path(self.model.get()), Path(self.output.get()),
                          {"Auto": "auto", "GPU preferred": "gpu", "CPU": "cpu"}.get(self.device.get(), "auto"), self.language.get())
        self.cancel.clear()
        self.results.clear()
        self.set_text(self.preview, "")
        for row in self.table.get_children():
            self.table.set(row, "status", "Queued")
        self.set_text(self.log, "")
        self.start_button.configure(state="disabled")
        self.add_button.configure(state="disabled")
        self.clear_button.configure(state="disabled")
        for widget in self.setting_widgets:
            widget.configure(state="disabled")
        self.device_box.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.start(12)
        jobs = list(enumerate(self.files))

        def work():
            completed = failed = 0
            try:
                for index, source in jobs:
                    if self.cancel.is_set():
                        break
                    self.events.put(("row", str(index), "Running"))
                    try:
                        result = transcribe(source, options, self.cancel,
                            lambda text: self.events.put(("status", text)))
                        self.events.put(("result", str(index), result))
                        completed += 1
                    except Cancelled:
                        self.events.put(("row", str(index), "Cancelled"))
                        break
                    except (ScribeError, OSError, UnicodeError) as exc:
                        failed += 1
                        self.events.put(("row", str(index), "Failed"))
                        self.events.put(("status", f"{source.name}: {exc}"))
            except Exception as exc:
                failed += 1
                self.events.put(("status", f"Unexpected error: {type(exc).__name__}: {exc}"))
            finally:
                self.events.put(("done", completed, failed, self.cancel.is_set()))
        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def cancel_batch(self):
        self.cancel.set()
        self.status.set("Cancelling the active job… Completed transcripts will be kept.")

    def poll(self):
        try:
            while True:
                message = self.events.get_nowait()
                kind = message[0]
                if kind == "status":
                    self.status.set(message[1].splitlines()[0])
                    self.set_text(self.log, message[1] + "\n", append=True)
                elif kind == "row":
                    self.table.set(message[1], "status", message[2])
                elif kind == "result":
                    row, result = message[1:]
                    self.results[row] = result.output
                    self.table.set(row, "status", "No text recognised" if result.empty else "Saved")
                    self.table.selection_set(row)
                    self.show_selected()
                elif kind == "done":
                    self.progress.stop()
                    self.start_button.configure(state="normal")
                    self.add_button.configure(state="normal")
                    self.clear_button.configure(state="normal")
                    for widget in self.setting_widgets:
                        widget.configure(state="normal")
                    self.device_box.configure(state="readonly")
                    self.cancel_button.configure(state="disabled")
                    self.status.set(f"{'Batch cancelled' if message[3] else 'Batch finished'}: {message[1]} saved, {message[2]} failed.")
        except queue.Empty:
            pass
        if self.closing and (not self.worker or not self.worker.is_alive()):
            self.window.destroy()
            return
        self.window.after(100, self.poll)

    def close(self):
        self.write_config()
        self.stop_audio()
        self.closing = True
        self.cancel.set()
        self.status.set("Stopping local transcription…")


def launch():
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError("No desktop display is available") from exc
    App(window)
    window.mainloop()
