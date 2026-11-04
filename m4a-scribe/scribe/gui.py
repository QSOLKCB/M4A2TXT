"""GTK 4 / libadwaita desktop. Inference stays in the existing local core."""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import re
import shutil
import subprocess
import time

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango
except (ImportError, ValueError) as exc:
    raise ImportError("Install python3-gi, gir1.2-gtk-4.0 and gir1.2-adw-1, then use /usr/bin/python3.") from exc

from . import __version__
from .core import ROOT, ScribeError
from .desktop import BatchController, PROFILES, Settings, processor_note, readiness, selected_profile
from .setup_progress import setup_fraction


def button(label, callback, icon=None):
    widget = Gtk.Button(label=label) if label else Gtk.Button(icon_name=icon)
    widget.connect("clicked", callback)
    return widget


def text_label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0, wrap=True)
    if style:
        widget.add_css_class(style)
    return widget


class ScribeWindow(Adw.ApplicationWindow):
    def __init__(self, application, *, controller=None, settings=None, root=ROOT):
        super().__init__(application=application, title="M4A2TXT", default_width=850, default_height=740)
        self.set_size_request(520, 500)
        self.root = root
        documents = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS) or str(Path.home() / "Documents")
        self.settings = settings or Settings(default_output=Path(documents) / "Transcripts")
        self.controller = controller or BatchController()
        self.rows = {}
        self.dialogs = []
        self.closing = False
        self.player = None
        self.progress_value = None
        self.last_busy = False
        self.setup_started = None
        self.detail_buffers = []
        self.setup_toast = None
        self.connect("close-request", self.on_close)

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="M4A2TXT", subtitle="Local audio transcription"))
        self.add_button = button(None, lambda _: self.choose_audio(), "list-add-symbolic")
        self.add_button.set_tooltip_text("Add audio files (Ctrl+O)")
        self.add_button.update_property([Gtk.AccessibleProperty.LABEL], ["Add audio files"])
        header.pack_start(self.add_button)
        self.details_button = button("Details", lambda _: self.show_details())
        header.pack_end(self.details_button)
        toolbar.add_top_bar(header)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar.set_content(scroller)
        clamp = Adw.Clamp(maximum_size=850, tightening_threshold=600)
        scroller.set_child(clamp)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                          margin_top=22, margin_bottom=22, margin_start=22, margin_end=22)
        clamp.set_child(content)
        content.append(text_label("Choose your machine", "title-2"))
        choices = Gtk.Box(spacing=10, homogeneous=True)
        content.append(choices)
        preset_style = Gtk.CssProvider()
        preset_style.load_from_data(b"""
            .machine-preset:checked {
                background-color: alpha(@accent_bg_color, 0.14);
                color: @window_fg_color;
                box-shadow: inset 0 0 0 2px @accent_bg_color;
            }
        """)
        self.profile_buttons = {}
        first = None
        for profile in PROFILES.values():
            choice = Gtk.ToggleButton()
            choice.add_css_class("card")
            choice.add_css_class("machine-preset")
            choice.get_style_context().add_provider(preset_style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                          margin_top=16, margin_bottom=16, margin_start=8, margin_end=8)
            heading = Gtk.Label(label=profile.title)
            heading.add_css_class("title-3")
            box.append(heading)
            description = Gtk.Label(label=profile.description, wrap=True, justify=Gtk.Justification.CENTER)
            description.add_css_class("caption")
            box.append(description)
            choice.set_child(box)
            if first:
                choice.set_group(first)
            else:
                first = choice
            choice.set_tooltip_text(f"{profile.title}: {profile.description}")
            self.profile_buttons[profile.key] = choice
            choice.connect("toggled", self.profile_changed, profile.key)
            choices.append(choice)
        processor = Gtk.Box(spacing=12)
        caption = text_label("Process with", "heading")
        caption.set_hexpand(True)
        processor.append(caption)
        devices = Gtk.Box(homogeneous=True)
        devices.add_css_class("linked")
        self.device_buttons = {}
        first = None
        for key, title in (("cpu", "CPU"), ("gpu", "GPU")):
            choice = Gtk.ToggleButton(label=title)
            choice.set_tooltip_text("Local CPU processing" if key == "cpu" else "Local NVIDIA CUDA processing")
            if first:
                choice.set_group(first)
            else:
                first = choice
            choice.connect("toggled", self.device_changed, key)
            self.device_buttons[key] = choice
            devices.append(choice)
        processor.append(devices)
        content.append(processor)
        self.mode_note = text_label("", "dim-label")
        content.append(self.mode_note)
        self.setup_banner = Adw.Banner(title="", use_markup=False)
        content.append(self.setup_banner)

        options = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        options.add_css_class("boxed-list")
        self.task_row = Adw.ComboRow(title="Task", model=Gtk.StringList.new(["Transcribe original speech", "Translate speech into English"]))
        self.task_row.set_selected(int(self.settings.task == "translate"))
        self.language_row = Adw.EntryRow(title="Source language code (en, fr, ja, auto…)")
        self.language_row.set_text(self.settings.language)
        self.format_row = Adw.ComboRow(title="Save as", model=Gtk.StringList.new(["Plain text (.txt)", "SubRip subtitles (.srt)", "WebVTT captions (.vtt)"]))
        self.format_row.set_selected(("txt", "srt", "vtt").index(self.settings.output_format))
        self.large_text_row = Adw.SwitchRow(title="Larger transcript text")
        self.large_text_row.set_active(self.settings.large_text)
        for row in (self.task_row, self.language_row, self.format_row, self.large_text_row):
            options.append(row)
        self.task_row.connect("notify::selected", self.options_changed)
        self.language_row.connect("changed", self.options_changed)
        self.format_row.connect("notify::selected", self.options_changed)
        self.large_text_row.connect("notify::active", self.options_changed)
        content.append(options)
        self.task_note = text_label("", "caption")
        content.append(self.task_note)

        queue_header = Gtk.Box(spacing=12)
        self.queue_heading = text_label("Audio files", "heading")
        self.queue_heading.set_hexpand(True)
        queue_header.append(self.queue_heading)
        self.clear_button = button("Clear", lambda _: self.clear())
        self.clear_button.add_css_class("flat")
        queue_header.append(self.clear_button)
        content.append(queue_header)
        self.queue_stack = Gtk.Stack(vhomogeneous=False)
        content.append(self.queue_stack)
        self.empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                             margin_top=16, margin_bottom=16)
        self.empty.append(Gtk.Image(icon_name="audio-x-generic-symbolic", pixel_size=48))
        empty_title = Gtk.Label(label="Audio in. Text out.")
        empty_title.add_css_class("title-2")
        self.empty.append(empty_title)
        self.empty.append(Gtk.Label(label="Drop audio files here, or use the + button to add audio.",
                                    wrap=True, justify=Gtk.Justification.CENTER))
        choose = button("Choose audio files…", lambda _: self.choose_audio())
        choose.set_halign(Gtk.Align.CENTER)
        self.empty.append(choose)
        self.queue_stack.add_named(self.empty, "empty")
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.queue_stack.add_named(self.listbox, "files")

        self.output_row = Adw.ActionRow(title="Save transcripts to", use_markup=False)
        self.output_row.set_subtitle_lines(2)
        self.folder_button = button("Change…", lambda _: self.choose_folder())
        self.folder_button.set_valign(Gtk.Align.CENTER)
        self.output_row.add_suffix(self.folder_button)
        self.output_row.set_activatable_widget(self.folder_button)
        output_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        output_box.add_css_class("boxed-list")
        output_box.append(self.output_row)
        content.append(output_box)
        content.append(text_label("Output preserves the recognizer’s text. Check important passages and caption timings against the audio.", "caption"))

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                         margin_top=12, margin_bottom=12, margin_start=22, margin_end=22)
        self.progress_row = Gtk.Box(spacing=10)
        self.setup_spinner = Gtk.Spinner()
        self.progress_row.append(self.setup_spinner)
        self.progress = Gtk.ProgressBar(hexpand=True)
        self.progress.set_visible(False)
        self.progress_row.append(self.progress)
        self.elapsed = text_label("", "dim-label")
        self.progress_row.append(self.elapsed)
        bottom.append(self.progress_row)
        self.log_hint = button("See Details For Log", lambda _: self.show_details())
        self.log_hint.add_css_class("flat")
        self.log_hint.add_css_class("caption")
        self.log_hint.set_halign(Gtk.Align.START)
        bottom.append(self.log_hint)
        actions = Gtk.Box(spacing=10)
        bottom.append(actions)
        self.status = text_label("Add audio files to begin.")
        self.status.set_hexpand(True)
        self.status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        actions.append(self.status)
        self.open_button = button(None, lambda _: self.open_folder(), "folder-open-symbolic")
        self.open_button.set_tooltip_text("Open transcript folder")
        self.open_button.update_property([Gtk.AccessibleProperty.LABEL], ["Open transcript folder"])
        actions.append(self.open_button)
        self.cancel_button = button("Cancel", lambda _: self.cancel_work())
        actions.append(self.cancel_button)
        self.primary_button = button("Transcribe", lambda _: self.primary())
        self.primary_button.add_css_class("suggested-action")
        self.primary_button.set_size_request(140, -1)
        actions.append(self.primary_button)
        toolbar.add_bottom_bar(bottom)

        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        target.connect("drop", self.on_drop)
        self.add_controller(target)
        self.drop_target = target
        for name, callback, keys in (("add", self.choose_audio, ["<Primary>o"]),
                                      ("transcribe", self.primary, ["<Primary>Return"]),
                                      ("cancel", self.cancel_work, ["Escape"]),
                                      ("folder", self.open_folder, ["<Primary>e"]),
                                      ("close", self.close, ["<Primary>q"])):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _v, cb=callback: cb())
            self.add_action(action)
            application.set_accels_for_action("win." + name, keys)
        self.device_buttons[self.settings.device].set_active(True)
        self.profile_buttons[self.settings.profile].set_active(True)
        self.refresh()
        self.poll_id = GLib.timeout_add(100, self.poll)

    @property
    def profile(self):
        return selected_profile(self.settings.profile, self.settings.task, self.settings.language)

    def options_changed(self, *_args):
        self.settings.task = ("transcribe", "translate")[self.task_row.get_selected()]
        self.settings.language = self.language_row.get_text().strip().lower()
        self.settings.output_format = ("txt", "srt", "vtt")[self.format_row.get_selected()]
        self.settings.large_text = self.large_text_row.get_active()
        self.save_settings()
        self.refresh()

    def toast(self, message):
        toast = Adw.Toast.new(str(message))
        self.toasts.add_toast(toast)
        return toast

    def save_settings(self):
        try:
            self.settings.save()
        except OSError as exc:
            self.toast(f"Could not remember your settings: {exc}")

    def profile_changed(self, widget, key):
        if not widget.get_active():
            return
        self.settings.profile = key
        if hasattr(self, "primary_button"):
            self.save_settings()
            self.refresh()

    def device_changed(self, widget, key):
        if not widget.get_active():
            return
        self.settings.device = key
        if hasattr(self, "primary_button"):
            self.save_settings()
            self.refresh()

    def add_paths(self, paths):
        errors = self.controller.add(paths)
        if errors:
            self.controller.logs.extend(errors)
            self.toast(errors[0])
        self.refresh()

    def on_drop(self, _target, value, _x, _y):
        if self.controller.busy or self.closing:
            return False
        paths = [file.get_path() for file in value.get_files() if file.get_path() is not None]
        if not paths:
            self.toast("Choose audio files stored on this computer.")
            return False
        self.add_paths(paths)
        return True

    def choose_audio(self):
        if self.controller.busy or self.closing:
            return
        dialog = Gtk.FileDialog(title="Choose audio files", modal=True)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        audio = Gtk.FileFilter(name="Audio files")
        for suffix in ("m4a", "mp4", "mp3", "wav", "flac", "aac", "ogg", "opus"):
            audio.add_pattern("*." + suffix)
            audio.add_pattern("*." + suffix.upper())
        filters.append(audio)
        dialog.set_filters(filters)
        self.dialogs.append(dialog)
        dialog.open_multiple(self, None, self.audio_chosen)

    def audio_chosen(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
            paths = [files.get_item(i).get_path() for i in range(files.get_n_items())]
            if any(path is None for path in paths):
                self.toast("Only files stored on this computer can be transcribed.")
            self.add_paths(path for path in paths if path is not None)
        except GLib.Error as exc:
            self.dialog_error(exc)
        finally:
            self.dialogs.remove(dialog)

    def dialog_error(self, exc):
        if not exc.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED) and not exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
            self.toast(exc.message)

    def choose_folder(self):
        if self.controller.busy or self.closing:
            return
        dialog = Gtk.FileDialog(title="Save transcripts in", modal=True)
        if self.settings.output.is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(self.settings.output)))
        self.dialogs.append(dialog)
        dialog.select_folder(self, None, self.folder_chosen)

    def folder_chosen(self, dialog, result):
        try:
            path = dialog.select_folder_finish(result).get_path()
            if path and not self.controller.busy:
                self.settings.output = Path(path)
                self.save_settings()
                self.refresh()
            elif path is None:
                self.toast("Choose a folder on this computer.")
        except GLib.Error as exc:
            self.dialog_error(exc)
        finally:
            self.dialogs.remove(dialog)

    def remove_job(self, identifier):
        self.controller.remove(identifier)
        self.refresh()

    def clear(self):
        self.controller.clear()
        self.refresh()

    def primary(self):
        if self.controller.busy or self.closing:
            return
        if self.setup_toast:
            self.setup_toast.dismiss()
            self.setup_toast = None
        try:
            if readiness(self.profile, self.root, self.settings.device):
                self.controller.setup(self.profile, self.root, device=self.settings.device)
            else:
                self.settings.output.mkdir(parents=True, exist_ok=True)
                self.controller.start(replace(self.profile.options(self.settings.output, self.root, self.settings.device),
                                              language=self.settings.language, task=self.settings.task,
                                              output_format=self.settings.output_format))
            self.progress_value = None
            self.save_settings()
            self.refresh()
        except (ScribeError, OSError) as exc:
            self.toast(exc)

    def cancel_work(self):
        self.controller.stop()
        self.status.set_text("Stopping… Completed transcripts will be kept.")

    def refresh(self):
        busy = self.controller.busy
        setup = busy and self.controller.operation == "setup"
        if setup and self.setup_started is None:
            self.setup_started = time.monotonic()
            self.status.set_text("Preparing setup…")
        elif not setup:
            self.setup_started = None
        self.progress_row.set_visible(busy)
        self.setup_spinner.set_visible(setup)
        self.setup_spinner.set_spinning(setup)
        self.elapsed.set_visible(setup)
        self.log_hint.set_visible(setup)
        self.progress.set_show_text(setup)
        missing = readiness(self.profile, self.root, self.settings.device)
        self.mode_note.set_text(processor_note(self.profile, self.root, self.settings.device))
        self.task_note.set_text(f"Model: {self.profile.model}. " + (
            "Translation produces English text; saved filenames include .en. Review against the source audio."
            if self.settings.task == "translate" else "Speech is kept in its source language. Timestamps in subtitle files come from the recognizer."))
        self.setup_banner.set_title(f"One-time setup for {self.profile.title} / {self.settings.device.upper()}: up to {self.profile.size} of model data. No audio is uploaded.")
        self.setup_banner.set_revealed(bool(missing) and not busy)
        self.output_row.set_subtitle(str(self.settings.output))
        self.queue_heading.set_text(f"Audio files · {len(self.controller.jobs)}" if self.controller.jobs else "Audio files")
        self.queue_stack.set_visible_child_name("files" if self.controller.jobs else "empty")
        live_ids = {job.id for job in self.controller.jobs}
        for identifier in list(self.rows):
            if identifier not in live_ids:
                self.listbox.remove(self.rows.pop(identifier)[0])
        for job in self.controller.jobs:
            if job.id not in self.rows:
                row = Adw.ActionRow(title=job.source.name, use_markup=False)
                row.set_title_lines(1)
                row.set_subtitle_lines(2)
                row.set_tooltip_text(str(job.source))
                view = button("View", lambda _b, j=job: self.show_transcript(j))
                view.set_valign(Gtk.Align.CENTER)
                remove = button(None, lambda _b, i=job.id: self.remove_job(i), "list-remove-symbolic")
                remove.set_tooltip_text("Remove " + job.source.name)
                remove.update_property([Gtk.AccessibleProperty.LABEL], ["Remove " + job.source.name])
                remove.set_valign(Gtk.Align.CENTER)
                row.add_suffix(view)
                row.add_suffix(remove)
                self.rows[job.id] = (row, view, remove)
                self.listbox.append(row)
            row, view, remove = self.rows[job.id]
            row.set_subtitle(f"{job.status} · {job.result.device}" if job.result else (
                job.status if not job.error else f"Failed — {job.error.splitlines()[0]}"))
            view.set_visible(job.result is not None)
            remove.set_sensitive(not busy)
        for choice in (*self.profile_buttons.values(), *self.device_buttons.values()):
            choice.set_sensitive(not busy)
        for widget in (self.add_button, self.folder_button, self.clear_button,
                       self.task_row, self.language_row, self.format_row):
            widget.set_sensitive(not busy)
        self.clear_button.set_sensitive(not busy and bool(self.controller.jobs))
        self.cancel_button.set_visible(busy)
        self.open_button.set_sensitive(self.settings.output.is_dir())
        self.primary_button.set_label("Setting up…" if busy and self.controller.operation == "setup" else (
            "Processing…" if busy else f"Set up {self.settings.device.upper()}" if missing else
            "Translate" if self.settings.task == "translate" else "Transcribe"))
        self.primary_button.set_sensitive(not busy and (bool(missing) or bool(self.controller.pending)))
        self.progress.set_visible(busy)
        if not busy:
            self.progress_value = None
            self.progress.set_fraction(0)
            self.progress.set_text(None)
            self.elapsed.set_text("")
            self.status.set_text(self.controller.summary or ("Ready when you are." if self.controller.jobs else "Add audio files to begin."))
        self.last_busy = busy

    def poll(self):
        events = self.controller.drain()
        for event in events:
            if event[0] in {"started", "message"}:
                if event[0] == "message":
                    self.status.set_text(event[1].splitlines()[0] if event[1] else "")
                    if self.controller.operation == "setup":
                        self.progress_value = setup_fraction(event[1])
                    else:
                        match = re.fullmatch(r"Whisper: (\d+)%", event[1])
                        self.progress_value = min(.99, int(match[1]) / 100) if match else None
                else:
                    self.progress_value = None
            elif event[0] == "setup-finished" and event[1]:
                self.setup_toast = self.toast("Setup complete. Transcription is ready to run offline.")
        if events or self.last_busy != self.controller.busy:
            self.refresh()
        if self.controller.busy:
            if self.controller.operation == "setup":
                elapsed = max(0, int(time.monotonic() - self.setup_started))
                self.elapsed.set_text(f"{elapsed // 60}:{elapsed % 60:02d} elapsed")
                if self.controller.cancel.is_set():
                    self.progress_value = None
                    self.status.set_text("Stopping local work before closing…" if self.closing else "Stopping setup…")
                self.progress.set_text("Stopping…" if self.controller.cancel.is_set() else (
                    f"{round(self.progress_value * 100)}%" if self.progress_value is not None else "Working…"))
            if self.progress_value is None:
                self.progress.pulse()
            else:
                self.progress.set_fraction(self.progress_value)
        if events and self.detail_buffers:
            text = self.details_text()
            for buffer in self.detail_buffers:
                buffer.set_text(text)
        if self.closing and not self.controller.busy:
            self.poll_id = None
            self.destroy()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def open_folder(self):
        try:
            Gio.AppInfo.launch_default_for_uri(self.settings.output.resolve().as_uri(), None)
        except (GLib.Error, OSError) as exc:
            self.toast(f"Could not open the folder: {exc}")

    def text_window(self, title, text, description):
        window = Adw.Window(transient_for=self, modal=True, title=title, default_width=720, default_height=560)
        window.set_destroy_with_parent(True)
        toolbar = Adw.ToolbarView()
        window.set_content(toolbar)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=title, subtitle=description))
        def copy_text(_button):
            buffer = view.get_buffer()
            window.get_clipboard().set(buffer.get_text(*buffer.get_bounds(), True))
        copy = button("Copy text", copy_text)
        header.pack_start(copy)
        toolbar.add_top_bar(header)
        view = Gtk.TextView(editable=False, cursor_visible=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            top_margin=18, bottom_margin=18, left_margin=18, right_margin=18)
        view.update_property([Gtk.AccessibleProperty.LABEL], [title])
        if self.settings.large_text:
            provider = Gtk.CssProvider()
            provider.load_from_data(b"textview { font-size: 20px; }")
            view.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        view.get_buffer().set_text(text)
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(view)
        toolbar.set_content(scroll)
        window.present()
        return window, toolbar, view.get_buffer()

    def details_text(self):
        text = "\n\n".join(self.controller.logs) or "No errors or operations yet."
        text += f"\n\nM4A2TXT {__version__}\nPreset: {self.profile.title}\nProcessor: {self.settings.device.upper()}\nModel: {self.profile.model}\n{processor_note(self.profile, self.root, self.settings.device)}"
        text += "\n\nFirst-time system packages on Ubuntu:\nsudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 ffmpeg git cmake build-essential\n\nThe Set up button downloads the selected model and builds missing local engines. NVIDIA acceleration also needs a compatible driver and CUDA toolkit."
        return text

    def show_details(self):
        window, _toolbar, buffer = self.text_window("Details", self.details_text(), "Local setup and diagnostics")
        self.detail_buffers.append(buffer)
        window.connect("close-request", lambda _window: self.detail_buffers.remove(buffer) or False)
        return window

    def show_transcript(self, job):
        if job.result is None:
            return None
        try:
            text = job.result.output.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self.toast(f"Could not open this transcript: {exc}")
            return None
        window, toolbar, _buffer = self.text_window(job.source.name, text, f"Machine output · {job.result.output.name}")
        controls = Gtk.Box(spacing=8, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        controls.append(button("Play audio", lambda _: self.play(job.source)))
        controls.append(button("Stop audio", lambda _: self.stop_audio()))
        toolbar.add_bottom_bar(controls)
        window.connect("close-request", lambda _w: self.stop_audio() or False)
        return window

    def play(self, source):
        ffplay = shutil.which("ffplay")
        if not ffplay:
            self.toast("Install FFmpeg with ffplay to play audio here.")
            return
        self.stop_audio()
        try:
            self.player = subprocess.Popen([ffplay, "-nodisp", "-autoexit", "-loglevel", "error",
                "-protocol_whitelist", "file,pipe", "-i", str(source)], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.toast(exc)

    def stop_audio(self):
        if self.player:
            if self.player.poll() is None:
                self.player.terminate()
                try:
                    self.player.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    self.player.kill()
                    self.player.wait()
            self.player = None

    def on_close(self, _window):
        self.closing = True
        self.stop_audio()
        self.controller.stop()
        self.status.set_text("Stopping local work before closing…")
        self.primary_button.set_sensitive(False)
        return True


class ScribeApplication(Adw.Application):
    def __init__(self, initial_files=(), **window_options):
        super().__init__(application_id="org.qsolkcb.M4A2TXT", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.initial_files = initial_files
        self.window_options = window_options
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = ScribeWindow(self, **self.window_options)
            self.window.add_paths(self.initial_files)
        self.window.present()


def launch(files=()):
    if (Gtk.get_major_version(), Gtk.get_minor_version()) < (4, 10) or (Adw.get_major_version(), Adw.get_minor_version()) < (1, 4):
        raise RuntimeError("The desktop needs GTK 4.10+ and libadwaita 1.4+ (Ubuntu 24.04 or newer).")
    if not Gtk.init_check():
        raise RuntimeError("No graphical desktop display is available.")
    return ScribeApplication(files).run(["m4a2txt"])
