"""Small standard-library desktop for the native Windows and macOS bundles."""
from dataclasses import replace
from pathlib import Path
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import ROOT, ScribeError
from .desktop import BatchController, Settings, readiness, selected_profile


class PortableWindow:
    def __init__(self, window, files=(), *, controller=None, settings=None):
        self.window = window
        self.controller = controller or BatchController()
        self.settings = settings or Settings()
        self.settings.device = "cpu"
        self.custom_model = None
        self.closing = False
        self.last_busy = False
        window.title("M4A2TXT — local transcription")
        window.geometry("820x720")
        window.minsize(640, 580)
        window.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(8, weight=1)
        ttk.Label(frame, text="Audio in. Text out.", font=("TkDefaultFont", 18, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self.controls = []
        self.profile = tk.StringVar(value=self.settings.profile)
        self.task = tk.StringVar(value=self.settings.task)
        self.language = tk.StringVar(value=self.settings.language)
        self.format = tk.StringVar(value=self.settings.output_format)
        self.large = tk.BooleanVar(value=self.settings.large_text)
        for row, label, variable, values in (
                (1, "Model preset", self.profile, ("laptop", "mid", "high")),
                (2, "Task (translation is into English)", self.task, ("transcribe", "translate")),
                (3, "Source language (en, fr, ja, auto…)", self.language, None),
                (4, "Output format", self.format, ("txt", "srt", "vtt"))):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            widget = ttk.Combobox(frame, textvariable=variable, values=values, state="readonly") if values else ttk.Entry(frame, textvariable=variable)
            widget.grid(row=row, column=1, columnspan=2, sticky="ew")
            self.controls.append(widget)
            variable.trace_add("write", self.changed)
        self.model_note = tk.StringVar()
        ttk.Label(frame, textvariable=self.model_note, wraplength=610).grid(row=5, column=0, columnspan=3, sticky="w", pady=6)
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=3, sticky="ew")
        for title, callback in (("Add audio…", self.add), ("Remove selected", self.remove),
                                ("Choose model file…", self.choose_model), ("Use preset", self.use_preset)):
            widget = ttk.Button(buttons, text=title, command=callback)
            widget.pack(side="left", padx=(0, 6))
            self.controls.append(widget)
        ttk.Label(frame, text="Queued audio — select a saved row and press Enter to read it").grid(row=7, column=0, columnspan=3, sticky="w", pady=(12, 4))
        self.jobs = ttk.Treeview(frame, columns=("file", "status"), show="headings", selectmode="extended", height=5)
        self.jobs.heading("file", text="Audio file")
        self.jobs.heading("status", text="Status")
        self.jobs.column("file", width=400)
        self.jobs.column("status", width=160)
        self.jobs.grid(row=8, column=0, columnspan=3, sticky="nsew")
        self.jobs.bind("<Return>", lambda _event: self.preview())
        self.jobs.bind("<Double-1>", lambda _event: self.preview())
        self.output = tk.StringVar(value=str(self.settings.output))
        ttk.Label(frame, textvariable=self.output, wraplength=610).grid(row=9, column=0, columnspan=2, sticky="w", pady=6)
        folder = ttk.Button(frame, text="Output folder…", command=self.choose_folder)
        folder.grid(row=9, column=2, sticky="e")
        self.controls.append(folder)
        ttk.Checkbutton(frame, text="Larger transcript text", variable=self.large, command=self.changed).grid(row=10, column=0, columnspan=2, sticky="w")
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.grid(row=11, column=0, columnspan=3, sticky="ew", pady=8)
        self.status = tk.StringVar(value="CPU processing. Your audio stays on this computer.")
        ttk.Label(frame, textvariable=self.status, wraplength=650).grid(row=12, column=0, columnspan=3, sticky="w")
        actions = ttk.Frame(frame)
        actions.grid(row=13, column=0, columnspan=3, sticky="ew", pady=12)
        ttk.Button(actions, text="Details", command=self.details).pack(side="left")
        ttk.Button(actions, text="Open output folder", command=self.open_folder).pack(side="left", padx=6)
        self.start_button = ttk.Button(actions, text="Transcribe", command=self.start)
        self.start_button.pack(side="right")
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.controller.stop)
        self.cancel_button.pack(side="right", padx=6)
        for modifier in ("Control", "Command") if sys.platform == "darwin" else ("Control",):
            window.bind(f"<{modifier}-o>", lambda _event: self.add())
            window.bind(f"<{modifier}-Return>", lambda _event: self.start())
            window.bind(f"<{modifier}-q>", lambda _event: self.close())
        window.bind("<Escape>", lambda _event: self.controller.stop())
        self.controller.add(files)
        self.refresh()
        window.after(100, self.poll)

    def effective_profile(self):
        return selected_profile(self.profile.get(), self.task.get(), self.language.get().strip().lower())

    def changed(self, *_args):
        if not hasattr(self, "start_button"):
            return
        self.settings.profile = self.profile.get()
        self.settings.task = self.task.get()
        self.settings.language = self.language.get().strip().lower()
        self.settings.output_format = self.format.get()
        self.settings.large_text = self.large.get()
        try:
            self.settings.save()
        except OSError as exc:
            self.status.set(f"Could not remember settings: {exc}")
        self.refresh()

    def add(self):
        if self.controller.busy or self.closing:
            return
        paths = filedialog.askopenfilenames(parent=self.window, title="Choose local audio files")
        errors = self.controller.add(paths)
        if errors:
            messagebox.showerror("Cannot add audio", "\n".join(errors), parent=self.window)
        self.refresh()

    def remove(self):
        for identifier in self.jobs.selection():
            self.controller.remove(int(identifier))
        self.refresh()

    def choose_model(self):
        if self.controller.busy:
            return
        path = filedialog.askopenfilename(parent=self.window, title="Choose installed GGML model", filetypes=[("GGML models", "*.bin")])
        if path:
            self.custom_model = Path(path)
            self.refresh()

    def use_preset(self):
        if not self.controller.busy:
            self.custom_model = None
            self.refresh()

    def choose_folder(self):
        if self.controller.busy:
            return
        path = filedialog.askdirectory(parent=self.window, initialdir=self.settings.output if self.settings.output.is_dir() else Path.home())
        if path:
            self.settings.output = Path(path)
            self.output.set(path)
            self.changed()

    def needs_setup(self):
        missing = readiness(self.effective_profile(), device="cpu")
        return [item for item in missing if item != "model download" or self.custom_model is None]

    def start(self):
        if self.controller.busy or self.closing:
            return
        try:
            if self.needs_setup():
                if self.custom_model:
                    raise ScribeError("The bundled CPU engine or FFmpeg is missing. Re-extract the complete package.")
                self.controller.setup(self.effective_profile(), device="cpu")
            else:
                self.settings.output.mkdir(parents=True, exist_ok=True)
                options = self.effective_profile().options(self.settings.output)
                self.controller.start(replace(options, model=self.custom_model or options.model,
                                              task=self.task.get(), language=self.language.get().strip().lower(),
                                              output_format=self.format.get()))
            self.changed()
        except (OSError, ScribeError) as exc:
            messagebox.showerror("Cannot start", str(exc), parent=self.window)
        self.refresh()

    def refresh(self):
        busy = self.controller.busy
        for widget in self.controls:
            widget.configure(state="disabled" if busy else "readonly" if isinstance(widget, ttk.Combobox) else "normal")
        for job in self.controller.jobs:
            key = str(job.id)
            values = (job.source.name, job.status)
            if self.jobs.exists(key):
                self.jobs.item(key, values=values)
            else:
                self.jobs.insert("", "end", iid=key, values=values)
        live = {str(job.id) for job in self.controller.jobs}
        for key in self.jobs.get_children():
            if key not in live:
                self.jobs.delete(key)
        profile = self.effective_profile()
        self.model_note.set(f"Model: {self.custom_model or profile.model}. CPU processing. " +
                            ("Translation saves English output with .en in the filename." if self.task.get() == "translate" else "Original speech language is preserved."))
        missing = self.needs_setup()
        label = f"Download model ({profile.size})" if missing else "Translate" if self.task.get() == "translate" else "Transcribe"
        self.start_button.configure(text="Working…" if busy else label, state="disabled" if busy or (not missing and not self.controller.pending) else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy != self.last_busy:
            self.progress.start(15) if busy else self.progress.stop()
        self.last_busy = busy

    def poll(self):
        events = self.controller.drain()
        if events:
            self.refresh()
            self.status.set(self.controller.message)
        if self.closing and not self.controller.busy:
            self.window.destroy()
            return
        self.window.after(100, self.poll)

    def text_window(self, title, text):
        popup = tk.Toplevel(self.window)
        popup.title(title)
        popup.geometry("760x520")
        bar = ttk.Frame(popup)
        bar.pack(fill="x")
        view = tk.Text(popup, wrap="word", font=("TkDefaultFont", 18 if self.large.get() else 12), padx=12, pady=12)
        view.insert("1.0", text)
        view.configure(state="disabled")
        def copy():
            popup.clipboard_clear()
            popup.clipboard_append(view.get("1.0", "end-1c"))
        ttk.Button(bar, text="Copy text", command=copy).pack(side="left", padx=8, pady=8)
        ttk.Button(bar, text="Close", command=popup.destroy).pack(side="right", padx=8)
        view.pack(fill="both", expand=True)
        popup.bind("<Escape>", lambda _event: popup.destroy())
        view.focus_set()
        return popup

    def preview(self):
        selected = self.jobs.selection()
        if selected:
            job = next(job for job in self.controller.jobs if str(job.id) == selected[0])
            try:
                if job.result:
                    self.text_window(job.result.output.name, job.result.output.read_text(encoding="utf-8"))
                elif job.error:
                    self.text_window("Job error", job.error)
            except (OSError, UnicodeError) as exc:
                messagebox.showerror("Cannot read output", str(exc), parent=self.window)

    def details(self):
        self.text_window("Details", "\n\n".join(self.controller.logs) or "No operations yet.")

    def open_folder(self):
        path = self.settings.output
        if path.is_dir():
            try:
                if sys.platform == "win32":
                    os.startfile(path)
                else:
                    subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
            except OSError as exc:
                messagebox.showerror("Cannot open folder", str(exc), parent=self.window)

    def close(self):
        self.closing = True
        self.controller.stop()
        self.start_button.configure(state="disabled")
        self.status.set("Stopping local work before closing…")


def launch(files=()):
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError(f"No graphical desktop display is available: {exc}") from exc
    PortableWindow(window, files)
    window.mainloop()
    return 0
