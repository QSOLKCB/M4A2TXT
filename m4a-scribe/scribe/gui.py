"""GTK 4 / libadwaita desktop. Inference stays in the existing local core."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

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
from .desktop import BatchController, PROFILES, Settings, processor_note, readiness


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
        self.mode_note = text_label("", "dim-label")
        content.append(self.mode_note)
        self.setup_banner = Adw.Banner(title="", use_markup=False)
        content.append(self.setup_banner)

        queue_header = Gtk.Box(spacing=12)
        self.queue_heading = text_label("Audio files", "heading")
        self.queue_heading.set_hexpand(True)
        queue_header.append(self.queue_heading)
        self.clear_button = button("Clear", lambda _: self.clear())
        self.clear_button.add_css_class("flat")
        queue_header.append(self.clear_button)
        content.append(queue_header)
        self.queue_stack = Gtk.Stack()
        content.append(self.queue_stack)
        self.empty = Adw.StatusPage(icon_name="audio-x-generic-symbolic",
            title="Audio in. Text out.", description="Drop audio files here, or use the + button to add audio.")
        self.empty.add_css_class("compact")
        self.empty.set_child(button("Choose audio files…", lambda _: self.choose_audio()))
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
        content.append(text_label("Plain text, with no summaries or rewriting. Check important passages against the audio.", "caption"))

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                         margin_top=12, margin_bottom=12, margin_start=22, margin_end=22)
        self.progress = Gtk.ProgressBar()
        self.progress.set_visible(False)
        bottom.append(self.progress)
        actions = Gtk.Box(spacing=10)
        bottom.append(actions)
        self.status = text_label("Add audio files to begin.")
        self.status.set_hexpand(True)
        self.status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        actions.append(self.status)
        self.open_button = button(None, lambda _: self.open_folder(), "folder-open-symbolic")
        self.open_button.set_tooltip_text("Open transcript folder")
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
                                      ("close", self.close, ["<Primary>q"])):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _v, cb=callback: cb())
            self.add_action(action)
            application.set_accels_for_action("win." + name, keys)
        self.profile_buttons[self.settings.profile].set_active(True)
        self.refresh()
        self.poll_id = GLib.timeout_add(100, self.poll)

    @property
    def profile(self):
        return PROFILES[self.settings.profile]

    def toast(self, message):
        self.toasts.add_toast(Adw.Toast.new(str(message)))

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
        try:
            if readiness(self.profile, self.root):
                self.controller.setup(self.profile, self.root)
            else:
                self.settings.output.mkdir(parents=True, exist_ok=True)
                self.controller.start(self.profile.options(self.settings.output, self.root))
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
        missing = readiness(self.profile, self.root)
        self.mode_note.set_text(processor_note(self.profile, self.root))
        self.setup_banner.set_title(f"One-time setup for {self.profile.title}: up to {self.profile.size} of model data. No audio is uploaded.")
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
                remove.set_valign(Gtk.Align.CENTER)
                row.add_suffix(view)
                row.add_suffix(remove)
                self.rows[job.id] = (row, view, remove)
                self.listbox.append(row)
            row, view, remove = self.rows[job.id]
            row.set_subtitle(job.status if not job.error else f"Failed — {job.error.splitlines()[0]}")
            view.set_visible(job.result is not None)
            remove.set_sensitive(not busy)
        for choice in self.profile_buttons.values():
            choice.set_sensitive(not busy)
        for widget in (self.add_button, self.folder_button, self.clear_button):
            widget.set_sensitive(not busy)
        self.clear_button.set_sensitive(not busy and bool(self.controller.jobs))
        self.cancel_button.set_visible(busy)
        self.open_button.set_sensitive(self.settings.output.is_dir())
        self.primary_button.set_label("Setting up…" if busy and self.controller.operation == "setup" else (
            "Transcribing…" if busy else f"Set up {self.profile.title}" if missing else "Transcribe"))
        self.primary_button.set_sensitive(not busy and (bool(missing) or bool(self.controller.pending)))
        self.progress.set_visible(busy)
        if not busy:
            self.status.set_text(self.controller.summary or ("Ready when you are." if self.controller.jobs else "Add audio files to begin."))
        self.last_busy = busy

    def poll(self):
        events = self.controller.drain()
        for event in events:
            if event[0] in {"started", "message"}:
                if event[0] == "message":
                    self.status.set_text(self.controller.message)
                    match = re.fullmatch(r"Whisper: (\d+)%", event[1])
                    self.progress_value = min(.99, int(match[1]) / 100) if match else None
                else:
                    self.progress_value = None
            elif event[0] == "setup-finished" and event[1]:
                self.toast("Setup complete. Transcription is ready to run offline.")
        if events or self.last_busy != self.controller.busy:
            self.refresh()
        if self.controller.busy:
            if self.progress_value is None:
                self.progress.pulse()
            else:
                self.progress.set_fraction(self.progress_value)
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
        copy = button("Copy text", lambda _: window.get_clipboard().set(text))
        header.pack_start(copy)
        toolbar.add_top_bar(header)
        view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            top_margin=18, bottom_margin=18, left_margin=18, right_margin=18)
        view.get_buffer().set_text(text)
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(view)
        toolbar.set_content(scroll)
        window.present()
        return window, toolbar

    def show_details(self):
        text = "\n\n".join(self.controller.logs) or "No errors or operations yet."
        text += f"\n\nM4A2TXT {__version__}\nMode: {self.profile.title}\nModel: {self.profile.model}\n{processor_note(self.profile, self.root)}"
        text += "\n\nFirst-time system packages on Ubuntu:\nsudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 ffmpeg git cmake build-essential\n\nThe Set up button downloads the selected model and builds missing local engines. NVIDIA acceleration also needs a compatible driver and CUDA toolkit."
        return self.text_window("Details", text, "Local setup and diagnostics")[0]

    def show_transcript(self, job):
        if job.result is None:
            return None
        try:
            text = job.result.output.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self.toast(f"Could not open this transcript: {exc}")
            return None
        window, toolbar = self.text_window(job.source.name, text, "Machine transcript · saved as plain text")
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
