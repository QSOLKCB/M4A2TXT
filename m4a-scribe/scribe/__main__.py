"""Entry point for the GUI and batch CLI."""
import argparse
from pathlib import Path
import signal
import sys
import threading

from . import __version__
from .core import Cancelled, Options, ScribeError, transcribe


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local audio to plain text. No cloud or server.")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--model", type=Path, help="Local whisper.cpp GGML .bin file")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    parser.add_argument("--device", choices=("auto", "cpu", "gpu"), default="auto",
                        help="gpu requests the CUDA engine; backend selection is engine-managed")
    parser.add_argument("--language", default="en")
    parser.add_argument("--threads", type=int, default=Options.__dataclass_fields__["threads"].default)
    parser.add_argument("--cpu-engine", type=Path, default=Options.__dataclass_fields__["cpu_engine"].default)
    parser.add_argument("--gpu-engine", type=Path, default=Options.__dataclass_fields__["gpu_engine"].default)
    args = parser.parse_args(argv)
    if args.gui or not args.files:
        try:
            from .gui import launch
            return launch(args.files)
        except (ImportError, RuntimeError) as exc:
            print(f"Desktop unavailable: {exc}\nUse the CLI, or install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 and launch with /usr/bin/python3 in a desktop session.", file=sys.stderr)
            return 2
    if not args.model:
        parser.error("--model is required for CLI transcription")
    cancel = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    options = Options(args.model, args.output_dir, args.device, args.language,
                      args.threads, args.cpu_engine, args.gpu_engine)
    failed = False
    for source in args.files:
        try:
            result = transcribe(source, options, cancel,
                                lambda message: print(message, file=sys.stderr, flush=True))
            print(result.output, flush=True)
        except Cancelled as exc:
            print(str(exc), file=sys.stderr)
            return 130
        except (ScribeError, OSError, UnicodeError) as exc:
            failed = True
            print(f"{source.name}: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
