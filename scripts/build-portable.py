#!/usr/bin/env python3
"""Build a native portable folder; run with the pinned packaging environment."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".portable-build"
WHISPER_PIN = "d1be6fde11ac6e0407606b4e42fe72d34add8037"


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_engine():
    source = WORK / "whisper-source"
    if not source.exists():
        run("git", "clone", "--depth", "1", "--branch", "v1.9.5", "https://github.com/ggml-org/whisper.cpp.git", source)
    if subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() != WHISPER_PIN:
        raise RuntimeError("Unexpected whisper.cpp source revision")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("Engine source is modified")
    build = WORK / "whisper-build"
    run("cmake", "-S", source, "-B", build, "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF",
        "-DWHISPER_BUILD_IS_DEV=OFF", "-DWHISPER_BUILD_TESTS=OFF", "-DWHISPER_BUILD_SERVER=OFF",
        "-DWHISPER_CURL=OFF", "-DGGML_RPC=OFF", "-DGGML_BACKEND_DL=OFF", "-DGGML_NATIVE=OFF",
        "-DGGML_CUDA=OFF", "-DGGML_METAL=OFF", "-DGGML_OPENMP=OFF", "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded")
    run("cmake", "--build", build, "--config", "Release", "--parallel", "4", "--target", "whisper-cli")
    name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    for candidate in (build / "bin/Release" / name, build / "bin" / name):
        if candidate.is_file():
            run(candidate, "--version")
            return candidate, source
    raise RuntimeError("Engine build did not produce whisper-cli")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    WORK.mkdir(exist_ok=True)
    engine, source = build_engine()
    ffmpeg = args.ffmpeg.resolve(strict=True)
    run(ffmpeg, "-version")
    # Rename the two tools consistently, independent of build configuration paths.
    tools = WORK / "tools"
    tools.mkdir(exist_ok=True)
    shutil.copy2(engine, tools / engine.name)
    shutil.copy2(ffmpeg, tools / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))
    destination = args.output_dir.resolve()
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--name", "M4A2TXT", "--distpath", str(destination), "--workpath", str(WORK / "pyinstaller"),
               "--specpath", str(WORK), "--paths", str(ROOT / "m4a-scribe"),
               "--hidden-import", "scribe.portable_gui", "--hidden-import", "scribe.models", "--exclude-module", "gi"]
    if sys.platform == "darwin":
        command += ["--windowed", "--osx-bundle-identifier", "org.qsolkcb.m4a2txt"]
    for tool in tools.iterdir():
        command += ["--add-binary", str(tool) + os.pathsep + "bin"]
    run(*command, ROOT / "m4a2txt")
    folder = destination / ("M4A2TXT.app" if sys.platform == "darwin" else "M4A2TXT")
    # Keep notices and LGPL source outside the signed macOS bundle. PyInstaller
    # applies an ad-hoc signature; this is not Developer ID notarization.
    payload = destination / f"M4A2TXT-{sys.platform}-{platform.machine().lower()}-portable"
    payload.mkdir()
    shutil.move(str(folder), payload / folder.name)
    shutil.copy2(ROOT / "LICENSE", payload / "REPOSITORY-LICENSE.txt")
    shutil.copy2(ROOT / "m4a-scribe/LICENSE", payload / "M4A-SCRIBE-LICENSE.txt")
    shutil.copy2(ROOT / "docs/PORTABLE.md", payload / "README.md")
    shutil.copy2(source / "LICENSE", payload / "WHISPER-LICENSE.txt")
    for name in ("ffmpeg-source.tar.gz", "FFMPEG-LICENSE.txt", "build-portable-ffmpeg.sh", "config.h", "config.log"):
        shutil.copy2(WORK / "ffmpeg" / name, payload / name)
    # Python and Tcl/Tk notices accompany the embedded runtimes.
    import tkinter
    tcl = tkinter.Tcl()
    for kind, base in (("python", Path(sys.base_prefix)), ("tcl", Path(tcl.eval("info library")))):
        for candidate in (base / "LICENSE.txt", base / "LICENSE", base / "license.terms"):
            if candidate.is_file():
                shutil.copy2(candidate, payload / (kind + "-" + candidate.name))
    distribution = importlib.metadata.distribution("pyinstaller")
    for item in distribution.files or ():
        if item.name.lower().startswith(("copying", "license")):
            location = Path(distribution.locate_file(item))
            if location.is_file():
                shutil.copy2(location, payload / ("pyinstaller-" + item.name))
    for index, location in enumerate(sorted(Path(sys.base_prefix).rglob("license.terms"))):
        shutil.copy2(location, payload / f"tcl-tk-{index}-license.terms")
    receipt = {"application_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "whisper_commit": WHISPER_PIN, "python": sys.version, "system": platform.platform(),
               "files": {p.relative_to(payload).as_posix(): digest(p) for p in sorted(payload.rglob("*")) if p.is_file()}}
    (payload / "BUILD-RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        archive = destination / (payload.name + ".tar.gz")
        with tarfile.open(archive, "w:gz") as out:
            out.add(payload, arcname=payload.name)
    else:
        archive = destination / (payload.name + ".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as out:
            for path in sorted(payload.rglob("*")):
                if path.is_file():
                    out.write(path, path.relative_to(destination))
    archive.with_name(archive.name + ".sha256").write_text(digest(archive) + "  " + archive.name + "\n", encoding="ascii")
    print(archive)


if __name__ == "__main__":
    main()
