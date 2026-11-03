#!/usr/bin/env python3
"""OPT fixture comparison: identical full suites, five alternating pairs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "m4a-scribe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    samples = []
    expected = None
    for pair in range(5):
        modes = ("fresh", "reused") if pair % 2 == 0 else ("reused", "fresh")
        for mode in modes:
            env = dict(os.environ, SCRIBE_TEST_FRESH_FIXTURES="1" if mode == "fresh" else "0")
            start = time.perf_counter()
            run = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                                 cwd=APP, env=env, text=True, capture_output=True, timeout=120)
            elapsed = time.perf_counter() - start
            if run.returncode:
                raise RuntimeError(run.stdout + run.stderr)
            tests = re.findall(r"^(test_\w+ \([^\n]+\)) \.\.\. ok$", run.stderr, re.MULTILINE)
            if not tests or "skipped" in run.stderr:
                raise RuntimeError("All cases must execute; empty/skipped test evidence is rejected")
            if expected is None:
                expected = tests
            if tests != expected:
                raise RuntimeError("Fresh/reused suites changed their test identity/order")
            samples.append({"pair": pair + 1, "mode": mode, "seconds": elapsed, "tests_passed": len(tests)})
            print(f"{mode}: {elapsed:.3f}s, {len(tests)} cases", flush=True)
    medians = {mode: statistics.median(s["seconds"] for s in samples if s["mode"] == mode)
               for mode in ("fresh", "reused")}
    cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), "unknown")
    record = {"kind": "OPT-INV-001 / OPT-PY-001 target test-stage characterization",
        "python": sys.version, "platform": platform.platform(), "cpu": cpu,
        "available_logical_cpus": len(os.sched_getaffinity(0)),
        "ffmpeg": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tested_file_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in (APP / "scribe", APP / "tests") for p in sorted(folder.glob("*.py"))},
        "test_ids": expected, "samples": samples, "median_seconds": medians,
        "speedup": medians["fresh"] / medians["reused"],
        "scope": "Full app test process including fixture setup/teardown; no inference speed claim"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"median_seconds": medians, "speedup": record["speedup"]}))


if __name__ == "__main__":
    main()
