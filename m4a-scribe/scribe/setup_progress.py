"""Read setup progress from streamed build and model-installer diagnostics."""
import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SetupLog:
    text: str


def setup_fraction(message: str) -> float | None:
    match = re.match(r"(?:Building (?:CPU|CUDA) engine|Downloading model|Copying model): (\d+)%", message)
    return min(1., int(match[1]) / 100) if match else None


class SetupOutput:
    """Handle split lines, Make/Ninja progress, and explicit setup stages.

    Only build percentages are monotonic: parallel build output can arrive out
    of order. A new stage returns the UI to activity mode rather than inventing
    a percentage for configuration, linking checks, or model verification.
    """
    def __init__(self, event: Callable[[str | SetupLog], None], engine: str | None = None):
        self.event = event
        self.engine = engine
        self.pending = b""
        self.percent = -1

    def feed(self, chunk: bytes) -> None:
        lines = re.split(rb"[\r\n]", self.pending + chunk)
        self.pending = lines.pop()[-8192:]
        for line in lines:
            self.line(line)

    def finish(self) -> None:
        if self.pending:
            self.line(self.pending)
            self.pending = b""

    def line(self, raw: bytes) -> None:
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw.decode("utf-8", errors="replace")).strip()
        if line:
            self.event(SetupLog(line))
        if line.startswith("Setup: "):
            self.percent = -1
            self.event(line.removeprefix("Setup: "))
        elif self.engine:
            make = re.match(r"\[\s*(\d+)%\]", line)
            ninja = re.match(r"\[(\d+)/(\d+)\]", line)
            percent = int(make[1]) if make else (
                int(ninja[1]) * 100 // int(ninja[2]) if ninja and int(ninja[2]) else -1)
            if 0 <= percent <= 100 and percent > self.percent:
                self.percent = percent
                self.event(f"Building {self.engine} engine: {percent}%")
