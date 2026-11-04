"""Offline orchestration. No HTTP clients, servers, or model downloads."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from typing import Callable

from .paths import ROOT, engine_path, ffmpeg_path
FORMATS = {".m4a": "mov", ".mp4": "mov", ".mp3": "mp3", ".wav": "wav",
           ".flac": "flac", ".aac": "aac", ".ogg": "ogg", ".opus": "ogg"}


class ScribeError(Exception):
    pass


class Cancelled(ScribeError):
    pass


class CudaMonitor:
    """Check backend diagnostics from the pinned whisper.cpp, not transcript text.

    A CUDA build can silently run on CPU. Stop on its explicit initialization
    failure and require a CUDA backend report before publishing a GPU result.
    This confirms backend selection, not a claim that every operation uses CUDA.
    """
    def __init__(self):
        self.pending = b""
        self.backend = None

    def feed(self, chunk: bytes) -> None:
        lines = (self.pending + chunk).split(b"\n")
        self.pending = lines.pop()[-2048:]
        for line in lines:
            if line.startswith(b"whisper_backend_init_gpu: no GPU found") or (
                    line.startswith(b"whisper_backend_init_gpu: failed to initialize ")):
                raise ScribeError("Whisper could not initialize a GPU backend.")
            match = re.fullmatch(rb"whisper_backend_init_gpu: using (CUDA[0-9]+) backend\s*", line)
            if match:
                self.backend = match[1].decode("ascii")

    def finish(self) -> str:
        self.feed(b"\n")
        if self.backend is None:
            raise ScribeError("Whisper did not report an active CUDA backend. The transcript was not saved.")
        return self.backend


@dataclass(frozen=True)
class Options:
    model: Path
    output_dir: Path
    device: str = "auto"
    language: str = "en"
    threads: int = max(1, min(8, (os.cpu_count() or 2) // 2))
    cpu_engine: Path = engine_path("cpu")
    gpu_engine: Path = engine_path("cuda")
    ffmpeg: str = ffmpeg_path()
    max_seconds: int = 4 * 3600
    task: str = "transcribe"
    output_format: str = "txt"


@dataclass(frozen=True)
class Result:
    output: Path
    device: str
    seconds: float
    source_sha256: str
    empty: bool


def check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise Cancelled("Cancelled; no final transcript was saved.")


def _stop(process: subprocess.Popen) -> None:
    """Reap the child and terminate its process group on Linux."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        pass
    # A child may have left a grandchild alive. Kill the original group too.
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass
    process.wait()


def run_process(argv: list[str], work: Path, cancel: threading.Event,
                event: Callable[[str], None], label: str,
                observer: Callable[[bytes], None] | None = None) -> str:
    """Use files for child output to avoid pipe deadlock; never invoke a shell."""
    check_cancel(cancel)
    # Separate file descriptions let Windows read live progress too, without
    # changing the offset used by the child or relying on POSIX-only pread.
    with tempfile.TemporaryDirectory(prefix="process-", dir=work) as logs:
        with (Path(logs) / "output.log").open("w+b") as log, (Path(logs) / "output.log").open("rb") as reader:
            try:
                process = subprocess.Popen(
                    argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=(os.name == "posix"), cwd=work,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as exc:
                raise ScribeError(f"Cannot start {label}: {exc}") from exc
            try:
                last_progress = -1
                observed = 0
                def inspect_log():
                    nonlocal observed
                    size = os.fstat(log.fileno()).st_size
                    if size > 64 * 1024 * 1024:
                        raise ScribeError(f"{label} produced an excessive diagnostic log.")
                    if observer:
                        while observed < size:
                            reader.seek(observed)
                            chunk = reader.read(min(65536, size - observed))
                            if not chunk:
                                break
                            observed += len(chunk)
                            observer(chunk)
                    return size

                while process.poll() is None:
                    if cancel.wait(0.1):
                        raise Cancelled("Cancelled; no final transcript was saved.")
                    size = inspect_log()
                    if size:
                        reader.seek(max(0, size - 8192))
                        tail = reader.read(8192)
                        matches = re.findall(rb"progress\s*=\s*(\d+)%", tail)
                        if matches:
                            progress = min(100, int(matches[-1]))
                            if progress > last_progress:
                                last_progress = progress
                                event(f"{label}: {progress}%")
                check_cancel(cancel)
                size = inspect_log()
                reader.seek(max(0, size - 16384))
                diagnostic = reader.read().decode("utf-8", errors="replace")
                if process.returncode:
                    raise ScribeError(f"{label} failed (exit {process.returncode}).\n{diagnostic[-4000:]}")
                return diagnostic
            except BaseException:
                _stop(process)
                raise


def snapshot_audio(source: Path, target: Path, cancel: threading.Event) -> str:
    """Copy one regular local file to private storage, hashing the exact input."""
    if source.is_symlink():
        raise ScribeError("Audio must be a regular local file, not a symlink.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    try:
        fd = os.open(source, flags)
    except OSError as exc:
        raise ScribeError(f"Cannot open audio: {exc}") from exc
    with os.fdopen(fd, "rb") as inp:
        before = os.fstat(inp.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ScribeError("Audio must be a regular local file.")
        if before.st_size == 0:
            raise ScribeError("The audio file is empty.")
        if before.st_size > 4 * 1024**3:
            raise ScribeError("This preview supports source files up to 4 GiB.")
        with target.open("xb") as out:
            remaining = before.st_size
            while remaining:
                check_cancel(cancel)
                chunk = inp.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ScribeError("The source changed while it was being copied.")
                out.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            after = os.fstat(inp.fileno())
            if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                    before.st_size, before.st_mtime_ns, before.st_ctime_ns):
                raise ScribeError("The source changed while it was being copied.")
    return digest.hexdigest()


def decode_audio(source: Path, wav: Path, options: Options,
                 cancel: threading.Event, event: Callable[[str], None]) -> None:
    exe = shutil.which(options.ffmpeg)
    if not exe:
        raise ScribeError("FFmpeg is missing. Install it using the README setup instructions.")
    event("Decoding audio locally…")
    run_process([
        str(Path(exe).resolve()), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-xerror", "-protocol_whitelist", "file,pipe", "-f", FORMATS[source.suffix.lower()],
        "-i", str(source), "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-t", str(options.max_seconds + 1), "-ar", "16000", "-ac", "1",
        "-c:a", "pcm_s16le", "-map_metadata", "-1", "-n", str(wav),
    ], wav.parent, cancel, event, "Audio decoder")
    try:
        with wave.open(str(wav), "rb") as audio:
            if audio.getnchannels() != 1 or audio.getframerate() != 16000 or audio.getsampwidth() != 2:
                raise ScribeError("The decoder returned an unexpected PCM format.")
            frames = audio.getnframes()
            if not frames:
                raise ScribeError("No audio samples were decoded.")
            if frames > options.max_seconds * 16000:
                raise ScribeError(f"Audio exceeds the {options.max_seconds / 3600:g}-hour preview limit; nothing was transcribed.")
    except (wave.Error, EOFError, RuntimeError) as exc:
        raise ScribeError("The decoder did not produce a valid WAV file.") from exc


def prepare_audio(source: Path, wav: Path, options: Options,
                  cancel: threading.Event, event: Callable[[str], None]) -> Path:
    """Reuse the private snapshot only when it already meets the PCM contract."""
    if source.suffix.lower() == ".wav":
        try:
            with wave.open(str(source), "rb") as audio:
                compatible = (audio.getnchannels(), audio.getframerate(), audio.getsampwidth(), audio.getcomptype()) == (1, 16000, 2, "NONE")
                if compatible:
                    frames = audio.getnframes()
                    if not 0 < frames <= options.max_seconds * 16000:
                        raise ScribeError("PCM audio is empty or exceeds the duration limit.")
                    remaining = frames * 2
                    while remaining:
                        check_cancel(cancel)
                        chunk = audio.readframes(min(remaining // 2, 524288))
                        if not chunk:
                            raise ScribeError("The PCM WAV file is truncated.")
                        remaining -= len(chunk)
        except (wave.Error, EOFError, RuntimeError):
            pass  # Let the strict decoder validate unsupported or malformed WAV layouts.
        else:
            if compatible:
                event("Using verified 16 kHz mono PCM audio directly…")
                return source
    decode_audio(source, wav, options, cancel, event)
    return wav


def validate_model_task(model: Path, options: Options) -> None:
    """Catch unsupported tasks even if a standard GGML model was renamed."""
    name = model.name.lower()
    english = bool(re.search(r"\.en(?:[.-]|$)", name))
    turbo = "turbo" in name
    with model.open("rb") as stream:
        header = stream.read(48)
    if len(header) == 48:
        fields = struct.unpack("<12i", header)
        if fields[0] == 0x67676D6C:
            english = english or fields[1] == 51864
            turbo = turbo or (fields[5], fields[9], fields[10]) == (32, 4, 128)
    if english and (options.task == "translate" or options.language != "en"):
        raise ScribeError("Choose a multilingual model for translation or a source language other than en.")
    if turbo and options.task == "translate":
        raise ScribeError("Turbo models are not trained for translation. Choose multilingual small or large-v3.")


def publish_text(source: Path, directory: Path, stem: str,
                 cancel: threading.Event, output_format: str = "txt") -> Path:
    """Publish complete bytes atomically without replacing any existing path."""
    if output_format not in {"txt", "srt", "vtt"}:
        raise ScribeError("Output format must be txt, srt, or vtt.")
    encoded_stem = stem.encode("utf-8")
    if len(encoded_stem) > 200:
        stem = encoded_stem[:180].decode("utf-8", errors="ignore") + "-" + hashlib.sha256(encoded_stem).hexdigest()[:12]
    fd, temporary = tempfile.mkstemp(prefix=".scribe-", suffix=".partial", dir=directory)
    staged = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        for index in range(10000):
            check_cancel(cancel)
            suffix = "" if index == 0 else f" ({index + 1})"
            candidate = directory / f"{stem}{suffix}.{output_format}"
            try:
                # Unlike replace/rename, link fails if candidate already exists.
                os.link(staged, candidate)
            except FileExistsError:
                continue
            except OSError as exc:
                raise ScribeError("Cannot safely publish on this filesystem; choose a local filesystem with hard-link support.") from exc
            return candidate
        raise ScribeError("Too many files already use this transcript name.")
    finally:
        staged.unlink(missing_ok=True)


def transcribe(source: Path, options: Options, cancel: threading.Event | None = None,
               event: Callable[[str], None] | None = None) -> Result:
    cancel = cancel if cancel is not None else threading.Event()
    event = event or (lambda message: None)
    started = time.monotonic()
    check_cancel(cancel)
    if options.device not in {"auto", "cpu", "gpu"}:
        raise ScribeError("Device must be auto, cpu, or gpu.")
    if options.task not in {"transcribe", "translate"}:
        raise ScribeError("Task must be transcribe or translate (into English).")
    if options.output_format not in {"txt", "srt", "vtt"}:
        raise ScribeError("Output format must be txt, srt, or vtt.")
    if not re.fullmatch(r"[a-z]{2,3}|auto", options.language):
        raise ScribeError("Use an ISO language code such as en, or auto.")
    if not 1 <= options.threads <= 256 or options.max_seconds < 1:
        raise ScribeError("Invalid thread count or duration limit.")
    # Deliberately do not interpret URLs or remote model identifiers.
    source = source.expanduser().absolute()
    if source.suffix.lower() not in FORMATS:
        raise ScribeError("Choose an M4A, MP4, MP3, WAV, FLAC, AAC, OGG, or OPUS file.")
    model = options.model.expanduser().resolve(strict=True)
    if not model.is_file() or model.stat().st_size == 0:
        raise ScribeError("Choose an installed whisper.cpp GGML model file (.bin).")
    validate_model_task(model, options)
    directory = options.output_dir.expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ScribeError("Choose an existing output folder.")

    cpu = options.cpu_engine.expanduser().resolve()
    gpu = options.gpu_engine.expanduser().resolve()
    candidates = [("CPU", cpu)]
    if options.device == "gpu":
        candidates = [("GPU", gpu)]
    elif options.device == "auto" and gpu.is_file() and os.access(gpu, os.X_OK):
        candidates = [("GPU", gpu), ("CPU fallback", cpu)]
    first_engine = candidates[0][1]
    if not first_engine.is_file() or not os.access(first_engine, os.X_OK):
        raise ScribeError(f"Engine is missing or not executable: {first_engine}\nSee scripts/build-engine.sh in the README.")

    with tempfile.TemporaryDirectory(prefix="m4a-scribe-") as temporary:
        work = Path(temporary)
        snapshot = work / ("source" + source.suffix.lower())
        event("Reading local audio…")
        source_hash = snapshot_audio(source, snapshot, cancel)
        wav = prepare_audio(snapshot, work / "audio.wav", options, cancel, event)
        chosen = ""
        textfile = work / ("transcript." + options.output_format)
        for attempt, (device, engine) in enumerate(candidates):
            check_cancel(cancel)
            textfile.unlink(missing_ok=True)
            event(f"Transcribing locally — {device}…")
            command = [str(engine), "--model", str(model), "--file", str(wav),
                       "--language", options.language, "--threads", str(options.threads),
                       "--output-" + options.output_format, "--output-file", str(work / "transcript"),
                       "--print-progress", "--temperature", "0", "--max-context", "0"]
            if options.task == "translate":
                command.append("--translate")
            # Keep Whisper's temperature retries for repetitive/low-confidence
            # decoding. These stay on the selected device; GPU mode still never
            # retries on CPU. Avoid carrying a bad text prediction into later
            # audio windows, where it can otherwise repeat for the rest of a file.
            monitor = CudaMonitor() if device == "GPU" else None
            if device.startswith("CPU"):
                command.extend(["--no-gpu", "--no-prints"])
            try:
                if not engine.is_file() or not os.access(engine, os.X_OK):
                    raise ScribeError(f"Engine is missing or not executable: {engine}")
                if monitor:
                    run_process(command, work, cancel, event, "Whisper", observer=monitor.feed)
                    backend = monitor.finish()
                    device = f"GPU ({backend})"
                    event(f"CUDA backend confirmed: {backend}.")
                else:
                    run_process(command, work, cancel, event, "Whisper")
                if not textfile.is_file():
                    raise ScribeError("Whisper exited without producing a transcript.")
                # Validate text encoding but do not rewrite the returned bytes.
                text = textfile.read_text(encoding="utf-8")
                chosen = device
                break
            except Cancelled:
                raise
            except ScribeError as exc:
                if attempt + 1 == len(candidates):
                    if options.device == "gpu":
                        raise ScribeError("GPU transcription failed. Check the NVIDIA driver and CUDA setup, "
                                          "try Mid for lower memory use, or select CPU. No CPU retry was started.\n"
                                          + str(exc)) from exc
                    raise
                event(f"GPU engine failed; retrying this file from the start on CPU.\n{exc}")
        check_cancel(cancel)
        stem = source.stem + (".en" if options.task == "translate" else "")
        output = publish_text(textfile, directory, stem, cancel, options.output_format)
        result = Result(output, chosen, time.monotonic() - started,
                        source_hash, not (text.removeprefix("WEBVTT").strip() if options.output_format == "vtt" else text))
        event(f"Saved: {output}" + (" — no text recognised" if result.empty else ""))
        return result
