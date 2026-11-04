#!/usr/bin/env python3
"""Explicit project-local CUDA 13.2 setup; never installs or replaces a driver.

Pinned Linux x86_64 redistributables from NVIDIA's redistrib_13.2.0.json.
CUDA 13.2 supports Blackwell, GCC 15 and the glibc 2.42 host toolchain.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / ".runtime/toolkit"
BASE = "https://developer.download.nvidia.com/compute/cuda/redist/"
COMPONENTS = {
    "cuda_nvcc": {
        "relative_path": "cuda_nvcc/linux-x86_64/cuda_nvcc-linux-x86_64-13.2.51-archive.tar.xz",
        "sha256": "706b996fefc59dc8d64d317fdf48d0aa84c4ae004eff43009dd918f40c5cc66a"
    },
    "cuda_crt": {
        "relative_path": "cuda_crt/linux-x86_64/cuda_crt-linux-x86_64-13.2.51-archive.tar.xz",
        "sha256": "fbc31fed55b7255591f3a19f575ca078827f5e6757d317d009f7ec1e69fcde4b"
    },
    "cuda_cudart": {
        "relative_path": "cuda_cudart/linux-x86_64/cuda_cudart-linux-x86_64-13.2.51-archive.tar.xz",
        "sha256": "539edc1056e44d319f2112e9971c6415d78d4dde04b3f6ffbd20ec808e718526"
    },
    "cuda_cccl": {
        "relative_path": "cuda_cccl/linux-x86_64/cuda_cccl-linux-x86_64-13.2.27-archive.tar.xz",
        "sha256": "56e1bafb29faa87375b0484814870046530b88c0a421909096892f027ec1927b"
    },
    "libnvvm": {
        "relative_path": "libnvvm/linux-x86_64/libnvvm-linux-x86_64-13.2.51-archive.tar.xz",
        "sha256": "e013fce38130d2337ea695aadc5ddd5dcfb78f9107903d72492b9819539749bb"
    },
    "libcublas": {
        "relative_path": "libcublas/linux-x86_64/libcublas-linux-x86_64-13.3.0.5-archive.tar.xz",
        "sha256": "9f3c23d55b098d9159c435db59f228df79493152a778d4d367e7d60470d8c64b"
    }
}


def unpack(archive: Path, destination: Path) -> None:
    # Each NVIDIA archive has one enclosing directory. Extract with Python's
    # data filter before merging, retaining library symlinks and licence files.
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        with tarfile.open(archive) as bundle:
            bundle.extractall(temp, filter="data")
        folders = list(Path(temp).iterdir())
        if len(folders) != 1 or not folders[0].is_dir():
            raise ValueError("Unexpected CUDA archive layout")
        shutil.copytree(folders[0], destination, dirs_exist_ok=True, symlinks=True)


def install(destination: Path = DESTINATION) -> None:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("This optional toolkit is for Linux x86_64. Use your platform's NVIDIA toolkit and CUDACXX.")
    marker = destination / "scribe-toolkit.json"
    if destination.exists():
        if marker.is_file() and json.loads(marker.read_text()) == COMPONENTS and (destination / "bin/nvcc").is_file():
            print(f"CUDA 13.2 already installed: {destination}")
            return
        raise ValueError(f"Incomplete or different toolkit at {destination}; move it aside before retrying.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cuda-install-", dir=destination.parent) as temp:
        work = Path(temp)
        stage = work / "toolkit"
        stage.mkdir()
        for name, item in COMPONENTS.items():
            print(f"Downloading and verifying {name}…", flush=True)
            archive = work / (name + ".tar.xz")
            digest = hashlib.sha256()
            with urllib.request.urlopen(BASE + item["relative_path"], timeout=120) as source, archive.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    target.write(chunk)
            if digest.hexdigest() != item["sha256"]:
                raise ValueError(f"SHA-256 mismatch for {name}; nothing installed.")
            unpack(archive, stage)
            archive.unlink()
        (stage / "scribe-toolkit.json").write_text(json.dumps(COMPONENTS, indent=2) + "\n")
        stage.rename(destination)
    print(f"CUDA 13.2 installed: {destination}")
    print("Run sh m4a-scribe/scripts/build-engine.sh cuda, or use Set up GPU in the app.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", required=True,
                        help="Download about 842 MiB of NVIDIA toolkit components into .runtime/toolkit")
    parser.parse_args()
    try:
        install()
    except (OSError, ValueError, tarfile.TarError) as exc:
        parser.exit(1, f"CUDA setup failed: {exc}\n")


if __name__ == "__main__":
    main()
