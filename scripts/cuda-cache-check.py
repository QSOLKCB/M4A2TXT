#!/usr/bin/env python3
"""Bounded CI compiler reuse with fresh-output canaries and clean rebuilds.

This helper owns only .compiler-cache and .cache-evidence in an isolated CI
checkout. It is not an application/transcript cache or a hardware GPU test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "m4a-scribe"
CACHE = ROOT / ".compiler-cache"
EVIDENCE = ROOT / ".cache-evidence"
ENGINE_CACHE = ROOT / ".engine-cache"
CONFIG = """direct_mode = false
compiler_check = content
sloppiness =
hard_link = false
file_clone = false
compression = true
max_size = 2G
"""
FLAGS = ("CC", "CXX", "CUDACXX", "CUDAHOSTCXX", "CFLAGS", "CXXFLAGS", "CPPFLAGS",
         "LDFLAGS", "CUDAFLAGS", "NVCC_PREPEND_FLAGS", "NVCC_APPEND_FLAGS",
         "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "LIBRARY_PATH",
         "SCRIBE_CUDA_ARCHITECTURES", "SCRIBE_BUILD_JOBS", "SCRIBE_BUILD_ONLY")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def output(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def tool_identity(name):
    path = Path(shutil.which(name) or name).resolve(strict=True)
    return {"path": str(path), "sha256": sha(path), "version": output([str(path), "--version"])}


def identity():
    cpu_keys = {"vendor_id", "cpu family", "model", "model name", "stepping", "flags"}
    cpu = sorted({line.strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                  if line.split(":", 1)[0].strip() in cpu_keys})
    return {"schema": 1, "system": platform.platform(), "cpu": cpu,
            "image": os.environ.get("ImageVersion"),
            "packages": output(["dpkg-query", "-W", "-f=${Package}=${Version}\n"]),
            "tools": {name: tool_identity(name) for name in
                      ("cc", "c++", "nvcc", "ccache", "cmake", "ld", "as", "ar", "ptxas", "fatbinary", "nvlink")},
            "environment": {key: os.environ.get(key, "") for key in FLAGS},
            "files": {name: sha(ROOT / name) for name in
                      ("m4a-scribe/scripts/build-engine.sh", "scripts/cuda-cache-check.py", ".github/workflows/cuda.yml")},
            "config": CONFIG}


def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2) + "\n"


def environment(cache):
    env = {key: value for key, value in os.environ.items() if not key.startswith("CCACHE_")}
    env.update(CCACHE_DIR=str(cache), CCACHE_CONFIGPATH=str(EVIDENCE / "ccache.conf"),
               CCACHE_EXTRAFILES=str(EVIDENCE / "toolchain.json"))
    for language in ("C", "CXX", "CUDA"):
        env[f"CMAKE_{language}_COMPILER_LAUNCHER"] = shutil.which("ccache")
    return env


def stats(env):
    return {key: int(value) for key, value in
            (line.split() for line in output(["ccache", "--print-stats"], env=env).splitlines())}


def hits(values):
    return values.get("direct_cache_hit", 0) + values.get("preprocessed_cache_hit", 0)


def write_input(path, content):
    path.write_text(content, encoding="utf-8")
    # Inputs are private and quiescent. Avoid ccache's same-second race guard
    # without enabling sloppiness; contents, not this timestamp, identify them.
    os.utime(path, (946684800, 946684800))


def canaries():
    records = []
    for compiler, suffix in (("c++", ".cpp"), ("nvcc", ".cu")):
        with tempfile.TemporaryDirectory(prefix="m4a2txt-cache-") as temp:
            folder = Path(temp)
            env = environment(folder / "cache")
            source, header, obj = folder / ("probe" + suffix), folder / "value.h", folder / "probe.o"
            code = '#include "value.h"\nextern "C" int value() { return VALUE + ADJUST; }\n'
            if compiler == "nvcc":
                code += '__global__ void probe(int *p) { *p = VALUE + ADJUST; }\n'
            write_input(source, code)
            arch = ["--objdir-as-tempdir", "-gencode=arch=compute_86,code=sm_86",
                    "-gencode=arch=compute_120a,code=sm_120a"] if suffix == ".cu" else []
            command = [shutil.which(compiler), "-O2", *arch, "-c", str(source), "-o", str(obj)]
            for name, value, adjust, expected_hit in (
                ("empty", 7, 1, False), ("unchanged_missing_output", 7, 1, True),
                ("changed_header", 9, 1, False), ("changed_flag", 9, 2, False),
                ("restored_input", 7, 1, True), ("corrupt_result", 7, 1, False),
            ):
                write_input(header, f"#define VALUE {value}\n")
                if name == "corrupt_result":
                    entries = list((folder / "cache").rglob("*R"))
                    if not entries:
                        raise RuntimeError("No cache results available for corruption canary")
                    for entry in entries:
                        if entry.is_file():
                            entry.write_bytes(b"deliberately damaged private canary result")
                obj.unlink(missing_ok=True)
                args = [*command, f"-DADJUST={adjust}"]
                subprocess.run(args, env=env, check=True, capture_output=True)
                reference = obj.read_bytes()
                obj.unlink()
                before = stats(env)
                subprocess.run(["ccache", *args], env=env, check=True, capture_output=True)
                after = stats(env)
                actual_hit = hits(after) > hits(before)
                if obj.read_bytes() != reference or actual_hit != expected_hit:
                    (EVIDENCE / f"{compiler}-{name}-fresh.o").write_bytes(reference)
                    shutil.copyfile(obj, EVIDENCE / f"{compiler}-{name}-cached.o")
                    (EVIDENCE / "canary-failure.json").write_text(encoded({
                        "compiler": compiler, "case": name, "expected_hit": expected_hit,
                        "actual_hit": actual_hit, "before": before, "after": after}))
                    raise RuntimeError(f"{compiler} {name}: parity/cache-state failure ({actual_hit=})")
                records.append({"compiler": compiler, "case": name, "sha256": sha(obj), "hit": actual_hit})
                (EVIDENCE / "canaries.json").write_text(encoded(records))
            obj.unlink()
            write_input(source, "this is not valid C++ or CUDA\n")
            entries_before = {str(p): sha(p) for p in (folder / "cache").rglob("*R") if p.is_file()}
            failed = subprocess.run(["ccache", *command], env=env, capture_output=True)
            entries_after = {str(p): sha(p) for p in (folder / "cache").rglob("*R") if p.is_file()}
            if failed.returncode == 0 or obj.exists() or entries_after != entries_before:
                raise RuntimeError(f"{compiler}: unsuccessful compilation was reused/published")
            records.append({"compiler": compiler, "case": "compiler_failure", "rejected": True})
    (EVIDENCE / "canaries.json").write_text(encoded(records))
    print("C++ and CUDA fresh/cached parity, invalidation, failure and corruption canaries passed", flush=True)


def builds(restored, count=3):
    env = environment(CACHE)
    records = []
    engine = APP / ".runtime/cuda/bin/whisper-cli"
    for index in range(count):
        if index:
            subprocess.run(["cmake", "--build", str(APP / ".runtime/cuda"), "--target", "clean"], env=env, check=True)
            if engine.exists():
                raise RuntimeError("Forced clean did not remove the engine")
        subprocess.run(["ccache", "--zero-stats"], env=env, check=True)
        start = time.perf_counter()
        with (EVIDENCE / f"build-{index}.log").open("w") as log:
            subprocess.run(["sh", "scripts/build-engine.sh", "cuda"], cwd=APP, env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        elapsed = time.perf_counter() - start
        record = {"phase": ("restored_first" if restored else "empty_first") if not index else f"clean_warm_{index}",
                  "seconds": elapsed, "engine_sha256": sha(engine), "stats": stats(env)}
        records.append(record)
        (EVIDENCE / "builds.json").write_text(encoded(records))
        if index and (record["engine_sha256"] != records[0]["engine_sha256"] or hits(record["stats"]) == 0):
            raise RuntimeError("Clean rebuild failed engine parity or did not reuse compiler work")
        print(f'{record["phase"]}: {elapsed:.2f}s; {hits(record["stats"])} hits', flush=True)
    if encoded(identity()) != (EVIDENCE / "toolchain.json").read_text():
        raise RuntimeError("CI toolchain/configuration changed during validation")
    subprocess.run(["ccache", "--cleanup"], env=env, check=True)
    median = statistics.median(record["seconds"] for record in records[1:]) if count > 1 else None
    result = {"restored": restored, "warm_median_seconds": median,
              "first_to_warm_ratio": records[0]["seconds"] / median if median else None,
              "scope": "Compiler/configure/link stage; excludes toolkit install and external cache transport; no GPU inference",
              "records": records}
    (EVIDENCE / "result.json").write_text(encoded(result))
    print(encoded(result), flush=True)


def save_engine():
    """Cache only the linked static engine and the configuration it was checked with."""
    ENGINE_CACHE.mkdir(exist_ok=True)
    names = {"whisper-cli": "bin/whisper-cli", "CMakeCache.txt": "CMakeCache.txt"}
    for name, relative in names.items():
        shutil.copy2(APP / ".runtime/cuda" / relative, ENGINE_CACHE / name)
    receipt = {"schema": 1, "identity": sha(EVIDENCE / "toolchain.json"),
               "files": {name: sha(ENGINE_CACHE / name) for name in names}}
    (ENGINE_CACHE / "receipt.json").write_text(encoded(receipt))


def restore_engine():
    """Reject incomplete, corrupt, symlinked or mismatched cache entries."""
    try:
        if any((ENGINE_CACHE / name).is_symlink() for name in ("receipt.json", "whisper-cli", "CMakeCache.txt")):
            return False
        receipt = json.loads((ENGINE_CACHE / "receipt.json").read_text())
        if receipt.get("schema") != 1 or receipt.get("identity") != sha(EVIDENCE / "toolchain.json"):
            return False
        files = receipt.get("files")
        if not isinstance(files, dict) or set(files) != {"whisper-cli", "CMakeCache.txt"}:
            return False
        if any(sha(ENGINE_CACHE / name) != digest for name, digest in files.items()):
            return False
        if not os.access(ENGINE_CACHE / "whisper-cli", os.X_OK):
            return False
    except (OSError, ValueError, AttributeError, TypeError):
        return False
    folder = APP / ".runtime/cuda"
    (folder / "bin").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ENGINE_CACHE / "whisper-cli", folder / "bin/whisper-cli")
    shutil.copy2(ENGINE_CACHE / "CMakeCache.txt", folder / "CMakeCache.txt")
    (EVIDENCE / "result.json").write_text(encoded({
        "engine_cache": "verified", "engine_sha256": sha(folder / "bin/whisper-cli"),
        "scope": "Exact toolchain/configuration and file digests verified; no new compilation or GPU inference"}))
    print("Reused the validated engine for this exact toolchain/configuration", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify", "build"))
    parser.add_argument("--restored", action="store_true")
    args = parser.parse_args()
    EVIDENCE.mkdir(exist_ok=True)
    if args.mode == "prepare":
        if CACHE.exists():
            raise RuntimeError("Prepare requires an isolated checkout without a pre-existing compiler cache")
        manifest = encoded(identity())
        (EVIDENCE / "toolchain.json").write_text(manifest)
        (EVIDENCE / "toolchain.json").chmod(0o444)
        (EVIDENCE / "ccache.conf").write_text(CONFIG)
        key = "cuda-objects-v1-" + hashlib.sha256(manifest.encode()).hexdigest()
        if path := os.environ.get("GITHUB_OUTPUT"):
            with open(path, "a") as stream:
                stream.write(f"key={key}\n")
                stream.write(f"engine_key=cuda-engine-v1-{hashlib.sha256(manifest.encode()).hexdigest()}\n")
        print(key)
    elif args.mode == "verify":
        canaries()
        builds(args.restored)
        save_engine()
    elif not restore_engine():
        print("No valid exact engine cache; building once with compiler reuse", flush=True)
        builds(args.restored, count=1)
        save_engine()


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        EVIDENCE.mkdir(exist_ok=True)
        (EVIDENCE / "command-failure.txt").write_text(
            str(exc) + "\n" + repr(exc.stdout) + "\n" + repr(exc.stderr) + "\n")
        raise
