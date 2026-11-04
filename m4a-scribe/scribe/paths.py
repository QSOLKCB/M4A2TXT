"""Separate read-only bundled tools from writable user models and settings."""
import os
from pathlib import Path
import sys

FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "m4a2txt"


ROOT = Path(os.environ["SCRIBE_DATA_HOME"]).expanduser() if os.environ.get("SCRIBE_DATA_HOME") else (
    user_data_dir() if FROZEN else RESOURCE_ROOT)
EXE = ".exe" if os.name == "nt" else ""


def engine_path(mode: str, root: Path = ROOT) -> Path:
    bundled = RESOURCE_ROOT / "bin" / ("whisper-cli" + EXE)
    if mode == "cpu" and root == ROOT and bundled.is_file():
        return bundled
    # Source builds live beside build-engine.sh, independently of model storage.
    runtime_root = RESOURCE_ROOT if root == ROOT else root
    return runtime_root / ".runtime" / mode / "bin" / ("whisper-cli" + EXE)


def ffmpeg_path() -> str:
    bundled = RESOURCE_ROOT / "bin" / ("ffmpeg" + EXE)
    return str(bundled) if bundled.is_file() else "ffmpeg"
