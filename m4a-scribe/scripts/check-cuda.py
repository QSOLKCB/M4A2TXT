#!/usr/bin/env python3
"""Transcribe the pinned public JFK sample with installed Mid/High CUDA models.

No downloads or setup happen here. This is an explicit local hardware check.
Its receipt records backend selection and transcript hashes, not an ASR score.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scribe.core import ROOT, ScribeError, transcribe
from scribe.desktop import PROFILES, readiness


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=("mid", "high"), action="append",
                        help="Repeat for both presets; defaults to Mid and High")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="New directory for sample transcripts and receipt.json")
    args = parser.parse_args()
    presets = list(dict.fromkeys(args.preset or ["mid", "high"]))
    for key in presets:
        missing = readiness(PROFILES[key], device="gpu")
        if missing:
            parser.error(f"Set up {key} / GPU first: {', '.join(missing)}")
    sample = ROOT / ".runtime/source/samples/jfk.wav"
    if not sample.is_file():
        parser.error("Pinned engine sample is missing. Run scripts/build-engine.sh cuda first.")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"kind": "local CUDA acceptance; public JFK sample; not an accuracy benchmark", "runs": []}
    with tempfile.TemporaryDirectory(prefix="m4a2txt-cuda-check-") as tmp:
        audio = Path(tmp) / "jfk.m4a"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-i", str(sample), "-c:a", "aac", str(audio)], check=True, timeout=60)
        receipt["source_wav_sha256"] = digest(sample)
        receipt["source_m4a_sha256"] = digest(audio)
        for key in presets:
            directory = output / key
            directory.mkdir()
            options = PROFILES[key].options(directory, device="gpu")
            result = transcribe(audio, options, event=lambda text: print(text, file=sys.stderr, flush=True))
            if result.empty:
                raise ScribeError("Public speech fixture produced an empty transcript.")
            receipt["runs"].append({"preset": key, "backend": result.device,
                "model": options.model.name, "model_sha256": digest(options.model),
                "engine_sha256": digest(options.gpu_engine), "seconds": result.seconds,
                "transcript_sha256": digest(result.output)})
    with (output / "receipt.json").open("x", encoding="utf-8") as file:
        json.dump(receipt, file, indent=2)
        file.write("\n")
    print(output / "receipt.json")


if __name__ == "__main__":
    main()
