#!/usr/bin/env python3
"""Build a deterministic application folder from committed Git objects."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"m4a2txt", "install-deps.sh", "LICENSE", "PACKAGING.md"}
APP_FILES = {"LICENSE", "README.md", "DESIGN.md", "VALIDATION.md", "SHA256SUMS", "run-scribe.sh"}


def selected(path):
    if path in ROOT_FILES:
        return True
    parts = PurePosixPath(path).parts
    if len(parts) < 2 or parts[0] != "m4a-scribe":
        return False
    relative = "/".join(parts[1:])
    if relative in APP_FILES or relative in {".gitignore", "models/.gitkeep"}:
        return True
    return (len(parts) == 3 and parts[1] in {"scribe", "scripts", "tests"}
            and parts[2].endswith((".py", ".sh"))) or (
        len(parts) == 3 and parts[1] == "validation"
        and parts[2] in {"cpu-smoke.json", "pipeline-tests.txt", "preview-0.1.0-SHA256SUMS"})


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def build(repo: Path, ref: str, output: Path) -> Path:
    commit = git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()
    timestamp = int(git(repo, "show", "-s", "--format=%ct", commit))
    files = {}
    for entry in git(repo, "ls-tree", "-rz", commit).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode("utf-8")
        if not selected(path):
            continue
        mode, kind, sha = metadata.decode().split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(f"Package input must be a regular file: {path}")
        name = "README.md" if path == "PACKAGING.md" else path
        files[name] = (git(repo, "cat-file", "blob", sha), int(mode, 8) & 0o777)
    required = {"m4a2txt", "install-deps.sh", "README.md", "LICENSE", "m4a-scribe/scribe/__init__.py",
                "m4a-scribe/scribe/launcher.py", "m4a-scribe/scribe/gui.py", "m4a-scribe/scribe/core.py"}
    if missing := required - files.keys():
        raise ValueError("Missing package inputs at that commit: " + ", ".join(sorted(missing)))
    for launcher in ("m4a2txt", "install-deps.sh"):
        if files[launcher][1] != 0o755:
            raise ValueError(f"{launcher} must be executable in Git")
    source = files["m4a-scribe/scribe/__init__.py"][0].decode()
    match = re.search(r'^__version__\s*=\s*[\'"]([0-9][A-Za-z0-9.+-]*)[\'"]\s*$', source, re.MULTILINE)
    if not match:
        raise ValueError("Cannot determine the package version")
    folder = "M4A2TXT-" + match[1]
    files["SOURCE_COMMIT.txt"] = ((commit + "\n").encode(), 0o644)
    files["SHA256SUMS"] = ("".join(
        hashlib.sha256(data).hexdigest() + "  " + name + "\n"
        for name, (data, _mode) in sorted(files.items())).encode(), 0o644)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (folder + "-linux.tar.gz")
    with archive.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
            directories = {folder}
            for name in files:
                directories.update(str(parent) for parent in (PurePosixPath(folder) / name).parents if str(parent) != ".")
            for name in sorted(directories):
                item = tarfile.TarInfo(name)
                item.type, item.mode, item.mtime = tarfile.DIRTYPE, 0o755, timestamp
                tar.addfile(item)
            for name, (data, mode) in sorted(files.items()):
                item = tarfile.TarInfo(folder + "/" + name)
                item.mode, item.size, item.mtime = mode, len(data), timestamp
                tar.addfile(item, io.BytesIO(data))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(checksum + "  " + archive.name + "\n", encoding="ascii")
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Committed Git revision; uncommitted edits are excluded")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    print(build(ROOT, args.ref, args.output_dir.resolve()))


if __name__ == "__main__":
    main()
