"""Display-independent desktop state, machine presets, and background jobs."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import threading
from typing import Callable

from .core import Cancelled, FORMATS, Options, ROOT, Result, ScribeError, run_process, transcribe
from .setup_progress import SetupLog, SetupOutput


@dataclass(frozen=True)
class Profile:
    key: str
    title: str
    description: str
    model: str
    size: str
    threads: int

    def options(self, output: Path, root: Path = ROOT, device: str = "cpu") -> Options:
        if device not in {"cpu", "gpu"}:
            raise ScribeError("Choose CPU or GPU processing.")
        return Options(root / "models" / f"ggml-{self.model}.bin", output,
                       device=device, threads=min(self.threads, os.cpu_count() or 1),
                       cpu_engine=root / ".runtime/cpu/bin/whisper-cli",
                       gpu_engine=root / ".runtime/cuda/bin/whisper-cli")


PROFILES = {
    "laptop": Profile("laptop", "Laptop", "Small model", "small.en", "466 MiB", 4),
    "mid": Profile("mid", "Mid", "Lower GPU memory", "large-v3-turbo-q5_0", "547 MiB", 4),
    "high": Profile("high", "High", "Full-size model", "large-v3", "2.9 GiB", 8),
}


def executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def readiness(profile: Profile, root: Path = ROOT, device: str = "cpu") -> list[str]:
    options = profile.options(Path.home(), root, device)
    missing = []
    if not shutil.which("ffmpeg"):
        missing.append("FFmpeg")
    engine = options.gpu_engine if device == "gpu" else options.cpu_engine
    if not executable(engine):
        missing.append("CUDA engine" if device == "gpu" else "CPU engine")
    if not options.model.is_file() or options.model.stat().st_size == 0:
        missing.append("model download")
    return missing


def processor_note(profile: Profile, root: Path = ROOT, device: str = "cpu") -> str:
    if device == "cpu":
        return "Uses your CPU. Audio stays on this computer."
    if executable(profile.options(Path.home(), root, device).gpu_engine):
        return "Uses your NVIDIA GPU via CUDA. GPU errors stop the job; select CPU to switch."
    return "Set up the CUDA engine to use your NVIDIA GPU. A compatible driver and CUDA toolkit are required."


def setup_profile(profile: Profile, cancel: threading.Event, event: Callable[[str | SetupLog], None],
                  root: Path = ROOT, device: str = "cpu") -> None:
    """Explicit setup only. Normal transcription never calls this function."""
    if not shutil.which("ffmpeg"):
        raise ScribeError("Install FFmpeg and the system packages listed in the setup guide first.")
    options = profile.options(Path.home(), root, device)
    engine = options.gpu_engine if device == "gpu" else options.cpu_engine
    needs_build = not executable(engine)
    # The build script discovers project-local toolkits and validates the GPU,
    # compiler and host headers before cloning or downloading a model.
    if needs_build:
        missing = [name for name in ("git", "cmake", "c++") if not shutil.which(name)]
        if missing:
            raise ScribeError("Install the setup packages first. Missing: " + ", ".join(missing))
    with tempfile.TemporaryDirectory(prefix="m4a2txt-setup-") as tmp:
        work = Path(tmp)
        if needs_build:
            mode = "cuda" if device == "gpu" else "cpu"
            event(f"Preparing the local {mode.upper()} engine…")
            progress = SetupOutput(event, mode.upper())
            run_process(["sh", str(root / "scripts/build-engine.sh"), mode], work, cancel, event,
                        "Engine setup", observer=progress.feed)
            progress.finish()
        event(f"Installing the {profile.title} model ({profile.size})…")
        progress = SetupOutput(event)
        run_process([sys.executable, str(root / "scripts/install-model.py"), profile.model,
                     "--download"], work, cancel, event, "Model setup", observer=progress.feed)
        progress.finish()
    if missing := readiness(profile, root, device):
        raise ScribeError("Setup incomplete: " + ", ".join(missing))


class Settings:
    def __init__(self, path: Path | None = None, default_output: Path | None = None):
        self.path = path or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "m4a-scribe/settings.json"
        self.profile = "laptop"
        self.device = "cpu"
        self.output = default_output or Path.home() / "Documents/Transcripts"
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if data.get("profile") in PROFILES:
                    self.profile = data["profile"]
                if data.get("device") in ("cpu", "gpu"):
                    self.device = data["device"]
                output = data.get("output")
                if isinstance(output, str) and output and Path(output).is_absolute():
                    self.output = Path(output)
        except (OSError, ValueError, TypeError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".settings-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump({"profile": self.profile, "device": self.device, "output": str(self.output)}, out, indent=2)
                out.write("\n")
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)


@dataclass
class Job:
    id: int
    source: Path
    status: str = "Ready"
    result: Result | None = None
    error: str = ""


class BatchController:
    """Workers publish events; the GTK/main thread alone mutates visible jobs."""
    def __init__(self, runner=transcribe):
        self.runner = runner
        self.jobs: list[Job] = []
        self.logs: deque[str] = deque(maxlen=500)
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self.active = False
        self.next_id = 1
        self.message = "Add audio files to begin."
        self.summary = ""
        self.operation = ""

    @property
    def busy(self) -> bool:
        return self.active or bool(self.thread and self.thread.is_alive())

    @property
    def pending(self) -> list[Job]:
        return [job for job in self.jobs if job.result is None]

    def add(self, paths) -> list[str]:
        if self.busy:
            return ["Wait for the current operation to finish before adding files."]
        known = {job.source for job in self.jobs}
        errors = []
        for item in paths:
            path = Path(os.path.abspath(Path(item).expanduser()))
            if path in known:
                continue
            if path.suffix.lower() not in FORMATS or path.is_symlink() or not path.is_file():
                errors.append(f"Choose a regular local audio file: {path.name}")
                continue
            self.jobs.append(Job(self.next_id, path))
            self.next_id += 1
            known.add(path)
        return errors

    def remove(self, identifier: int) -> None:
        if not self.busy:
            self.jobs[:] = [job for job in self.jobs if job.id != identifier]

    def clear(self) -> None:
        if not self.busy:
            self.jobs.clear()

    def _begin(self, operation: str) -> None:
        if self.busy:
            raise ScribeError("An operation is already running.")
        self.cancel.clear()
        self.logs.clear()
        self.summary = ""
        self.active = True
        self.operation = operation

    def start(self, options: Options) -> None:
        if not self.pending:
            raise ScribeError("Add a new audio file to transcribe.")
        self._begin("transcription")
        snapshot = [(job.id, job.source) for job in self.pending]
        for job in self.pending:
            job.status, job.error = "Queued", ""

        def work():
            completed = failed = 0
            try:
                for identifier, path in snapshot:
                    if self.cancel.is_set():
                        break
                    self.events.put(("started", identifier))
                    try:
                        result = self.runner(path, options, self.cancel,
                            lambda text: self.events.put(("message", text)))
                        self.events.put(("result", identifier, result))
                        completed += 1
                    except Cancelled:
                        self.events.put(("cancelled", identifier))
                        break
                    except Exception as exc:
                        failed += 1
                        self.events.put(("failed", identifier, str(exc)))
            finally:
                self.events.put(("finished", completed, failed, self.cancel.is_set()))
        self.thread = threading.Thread(target=work, daemon=False)
        self.thread.start()

    def setup(self, profile: Profile, root: Path = ROOT, installer=setup_profile, device: str = "cpu") -> None:
        self._begin("setup")

        def update(value):
            self.events.put(("log", value.text) if isinstance(value, SetupLog) else ("message", value))

        def work():
            success = False
            try:
                installer(profile, self.cancel, update, root, device)
                success = True
            except Cancelled:
                pass
            except Exception as exc:
                self.events.put(("message", str(exc)))
            finally:
                self.events.put(("setup-finished", success, self.cancel.is_set()))
        self.thread = threading.Thread(target=work, daemon=False)
        self.thread.start()

    def stop(self) -> None:
        self.cancel.set()

    def drain(self) -> list[tuple]:
        drained = []
        by_id = {job.id: job for job in self.jobs}
        for _ in range(200):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            drained.append(event)
            kind = event[0]
            if kind == "message":
                self.message = event[1].splitlines()[0] if event[1] else ""
                self.logs.append(event[1])
            elif kind == "log":
                self.logs.append(event[1])
            elif kind == "started":
                by_id[event[1]].status = "Transcribing"
            elif kind == "result":
                job = by_id[event[1]]
                job.result = event[2]
                job.status = "No text recognised" if job.result.empty else "Saved"
            elif kind in {"failed", "cancelled"}:
                job = by_id[event[1]]
                job.status = "Failed" if kind == "failed" else "Cancelled"
                job.error = event[2] if kind == "failed" else ""
                if job.error:
                    self.logs.append(f"{job.source.name}: {job.error}")
            elif kind == "finished":
                self.active = False
                self.summary = f"{event[1]} saved · {event[2]} failed"
                if event[3]:
                    self.summary = "Stopped · " + self.summary
                    for job in self.pending:
                        if job.status == "Queued":
                            job.status = "Not started"
                self.message = self.summary
            elif kind == "setup-finished":
                self.active = False
                self.summary = "Setup complete. You can transcribe offline." if event[1] else (
                    "Setup cancelled." if event[2] else "Setup failed. Open Details for the reason.")
                self.message = self.summary
        return drained
