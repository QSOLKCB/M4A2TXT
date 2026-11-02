"""Offline orchestration. No HTTP clients, servers, or model downloads."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
FORMATS = {".m4a": "mov", ".mp4": "mov", ".mp3": "mp3", ".wav": "wav",
           ".flac": "flac", ".aac": "aac", ".ogg": "ogg", ".opus": "ogg"}


class ScribeError(Exception):
    pass


class Cancelled(ScribeError):
    pass


@dataclass(frozen=True)
class Options:
    model: Path
    output_dir: Path
    device: str = "auto"
    language: str = "en"
    threads: int = max(1, min(8, (os.cpu_count() or 2) // 2))
    cpu_engine: Path = ROOT / ".runtime" / "cpu" / "bin" / "whisper-cli"
    gpu_engine: Path = ROOT / ".runtime" / "cuda" / "bin" / "whisper-cli"
    ffmpeg: str = "ffmpeg"
    max_seconds: int = 4 * 3600


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
                event: Callable[[str], None], label: str) -> str:
    """Use files for child output to avoid pipe deadlock; never invoke a shell."""
    check_cancel(cancel)
    with tempfile.TemporaryFile(dir=work) as log:
        try:
            process = subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=(os.name == "posix"), cwd=work,
            )
        except OSError as exc:
            raise ScribeError(f"Cannot start {label}: {exc}") from exc
        try:
            last_progress = -1
            while process.poll() is None:
                if cancel.wait(0.1):
                    raise Cancelled("Cancelled; no final transcript was saved.")
                # pread does not alter the file position shared with the child.
                size = os.fstat(log.fileno()).st_size
                if size > 64 * 1024 * 1024:
                    raise ScribeError(f"{label} produced an excessive diagnostic log.")
                if hasattr(os, "pread") and size:
                    tail = os.pread(log.fileno(), min(size, 8192), max(0, size - 8192))
                    matches = re.findall(rb"progress\s*=\s*(\d+)%", tail)
                    if matches:
                        progress = min(100, int(matches[-1]))
                        if progress > last_progress:
                            last_progress = progress
                            event(f"{label}: {progress}%")
            check_cancel(cancel)
            log.seek(max(0, os.fstat(log.fileno()).st_size - 16384))
            diagnostic = log.read().decode("utf-8", errors="replace")
            if process.returncode:
                raise ScribeError(f"{label} failed (exit {process.returncode}).\n{diagnostic[-4000:]}")
            return diagnostic
        except BaseException:
            _stop(process)
            raise


def snapshot_audio(source: Path, target: Path, cancel: threading.Event) -> str:
    """Copy one regular local file to private storage, hashing the exact input."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
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
    except (wave.Error, EOFError) as exc:
        raise ScribeError("The decoder did not produce a valid WAV file.") from exc


def publish_text(source: Path, directory: Path, stem: str,
                 cancel: threading.Event) -> Path:
    """Publish complete bytes atomically without replacing any existing path."""
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
            candidate = directory / f"{stem}{suffix}.txt"
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
    directory = options.output_dir.expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ScribeError("Choose an existing output folder.")

    cpu = options.cpu_engine.expanduser().resolve()
    gpu = options.gpu_engine.expanduser().resolve()
    candidates = [("CPU", cpu)]
    if options.device == "gpu":
        candidates = [("GPU preferred", gpu)]
    elif options.device == "auto" and gpu.is_file() and os.access(gpu, os.X_OK):
        candidates = [("GPU preferred", gpu), ("CPU fallback", cpu)]
    first_engine = candidates[0][1]
    if not first_engine.is_file() or not os.access(first_engine, os.X_OK):
        raise ScribeError(f"Engine is missing or not executable: {first_engine}\nSee scripts/build-engine.sh in the README.")

    with tempfile.TemporaryDirectory(prefix="m4a-scribe-") as temporary:
        work = Path(temporary)
        snapshot = work / ("source" + source.suffix.lower())
        event("Reading local audio…")
        source_hash = snapshot_audio(source, snapshot, cancel)
        wav = work / "audio.wav"
        decode_audio(snapshot, wav, options, cancel, event)
        chosen = ""
        textfile = work / "transcript.txt"
        for attempt, (device, engine) in enumerate(candidates):
            check_cancel(cancel)
            textfile.unlink(missing_ok=True)
            event(f"Transcribing locally — {device}…")
            command = [str(engine), "--model", str(model), "--file", str(wav),
                       "--language", options.language, "--threads", str(options.threads),
                       "--output-txt", "--output-file", str(work / "transcript"),
                       "--print-progress", "--no-prints", "--temperature", "0",
                       "--no-fallback"]
            if device.startswith("CPU"):
                command.append("--no-gpu")
            try:
                if not engine.is_file() or not os.access(engine, os.X_OK):
                    raise ScribeError(f"Engine is missing or not executable: {engine}")
                run_process(command, work, cancel, event, "Whisper")
                if not textfile.is_file():
                    raise ScribeError("Whisper exited without producing a transcript.")
                # Validate text encoding but do not rewrite the returned bytes.
                textfile.read_text(encoding="utf-8")
                chosen = device
                break
            except Cancelled:
                raise
            except ScribeError as exc:
                if attempt + 1 == len(candidates):
                    raise
                event(f"GPU engine failed; retrying this file from the start on CPU.\n{exc}")
        check_cancel(cancel)
        output = publish_text(textfile, directory, source.stem, cancel)
        result = Result(output, chosen, time.monotonic() - started,
                        source_hash, textfile.stat().st_size == 0)
        event(f"Saved: {output}" + (" — no text recognised" if result.empty else ""))
        return result
