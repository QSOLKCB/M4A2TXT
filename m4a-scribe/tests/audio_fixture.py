"""One immutable fixture contract; each consumer gets its own writable file."""
from pathlib import Path
import subprocess
import tempfile


FIXED_M4A_FIXTURE = ("-hide_banner", "-loglevel", "error", "-f", "lavfi",
                     "-i", "sine=frequency=440:duration=0.25", "-c:a", "aac")


def encode_fixture(path: Path) -> None:
    subprocess.run(["ffmpeg", *FIXED_M4A_FIXTURE, str(path)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def fixture_bytes() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.m4a"
        encode_fixture(path)
        return path.read_bytes()
