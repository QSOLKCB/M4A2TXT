#!/usr/bin/env python3
"""Explicit model setup, invoked by the setup button or manually via the CLI."""
import argparse
import hashlib
import os
import signal
from pathlib import Path
import sys
import tempfile
import urllib.request

# Expected file digests from whisper.cpp v1.9.5 models/README.md.
# Upstream publishes SHA-1 here. SHA-256 is additionally recorded locally.
MODELS = {
    "large-v3-turbo": "4af2b29d7ec73d781377bfd1758ca957a807e941",
    "large-v3-turbo-q5_0": "e050f7970618a659205450ad97eb95a18d69c9ee",
    "large-v3": "ad82bf6a9043ceed055076d0fd39f5f186ff8062",
    "small.en": "db8a495a91d927739e50b3fc1cc4c6b8f6c2d022",
    "tiny.en": "c78c86eb1a8faa21b369bcd33207cc90d64ae9df",
}
ROOT = Path(__file__).resolve().parents[1]


def digests(path):
    sha1, sha256 = hashlib.sha1(), hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha1.update(block)
            sha256.update(block)
    return sha1.hexdigest(), sha256.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Install a local Whisper model. Download requires an explicit --download.")
    parser.add_argument("model", choices=MODELS)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--download", action="store_true")
    source.add_argument("--from-file", type=Path)
    parser.add_argument("--directory", type=Path, default=ROOT / "models")
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"ggml-{args.model}.bin"
    target = directory / filename
    expected = MODELS[args.model]
    if target.exists() or target.is_symlink():
        if not target.is_symlink() and target.is_file():
            actual, sha256 = digests(target)
            if actual == expected:
                print(f"Already installed: {target}\nSHA-256: {sha256}")
                return 0
        parser.error(f"An existing model differs from the expected file: {target}. It has not been replaced.")
    fd, temporary = tempfile.mkstemp(prefix=".model-", suffix=".partial", dir=directory)
    staged = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as out:
            if args.download:
                url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{filename}"
                print(f"Downloading {args.model} from Hugging Face. No audio is involved.", flush=True)
                stream = urllib.request.urlopen(url, timeout=60)
            else:
                stream = args.from_file.expanduser().open("rb")
            with stream:
                size, reported = 0, 0
                while block := stream.read(1024 * 1024):
                    size += len(block)
                    if size > 4 * 1024**3:
                        raise ValueError("Model exceeds the 4 GiB download limit.")
                    out.write(block)
                    if size - reported >= 128 * 1024**2:
                        print(f"Received {size // 1024**2} MiB", flush=True)
                        reported = size
            out.flush()
            os.fsync(out.fileno())
        actual, sha256 = digests(staged)
        if actual != expected:
            raise ValueError(f"Model integrity check failed: expected upstream SHA-1 {expected}, received {actual}.")
        os.link(staged, target)  # no clobber if another setup races us
        # This digest records locally installed bytes; it is not a signature.
        receipt = target.with_suffix(".bin.sha256")
        try:
            with receipt.open("x", encoding="ascii") as out:
                out.write(f"{sha256}  {filename}\n")
        except FileExistsError:
            print(f"An older checksum receipt already exists at {receipt}; it was preserved.", file=sys.stderr)
        print(f"Installed: {target}\nSHA-256: {sha256}")
        return 0
    finally:
        staged.unlink(missing_ok=True)


if __name__ == "__main__":
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Model setup cancelled.", file=sys.stderr)
        raise SystemExit(130)
    except (OSError, ValueError) as exc:
        print(f"Model setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
