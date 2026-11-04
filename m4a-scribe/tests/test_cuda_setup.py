"""Exercise setup commands without downloads, root privileges or a real GPU."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

APP = Path(__file__).resolve().parents[1]
PIN = "d1be6fde11ac6e0407606b4e42fe72d34add8037"
TOOLS = '''#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["TOOL_LOG"], "a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
if name == "nvcc":
    old = "old" in sys.argv[0]
    if args == ["--version"]:
        print("Cuda compilation tools, release " + ("12.4" if old else "13.2"))
    elif args == ["--list-gpu-code"]:
        print("sm_86" if old else "sm_86\\nsm_120")
    elif os.environ.get("FAIL_HOST"):
        sys.exit("unsupported host compiler")
elif name == "nvidia-smi":
    if os.environ.get("NO_GPU"):
        sys.exit("driver unavailable")
    print("12.0")
elif name == "git":
    if "rev-parse" in args:
        print("PIN")
elif name == "cmake" and "-B" in args:
    build = pathlib.Path(args[args.index("-B") + 1])
    (build / "bin").mkdir(parents=True, exist_ok=True)
    engine = build / "bin/whisper-cli"
    engine.write_text("#!/bin/sh\\nexit 0\\n")
    engine.chmod(0o755)
'''.replace('"PIN"', repr(PIN))


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cuda test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        shutil.copyfile(APP / "scripts/build-engine.sh", self.root / "scripts/build-engine.sh")
        (self.root / ".runtime/source/.git").mkdir(parents=True)
        self.bin = self.root / "old tools"
        self.bin.mkdir()
        for name in ("nvcc", "git", "cmake", "nvidia-smi"):
            self.tool(self.bin / name)
        self.local = self.root / ".runtime/toolkit/bin/nvcc"
        self.tool(self.local)
        self.log = self.root / "calls.jsonl"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("SCRIBE_", "CUDA", "NVCC_"))}
        self.env.update(PATH=str(self.bin) + os.pathsep + os.environ["PATH"], TOOL_LOG=str(self.log))

    def tool(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TOOLS)
        path.chmod(0o755)

    def run_build(self, mode="cuda", **env):
        return subprocess.run(["sh", str(self.root / "scripts/build-engine.sh"), mode],
                              env={**self.env, **env}, capture_output=True, text=True, timeout=15)

    def calls(self, name):
        return [c[1:] for c in map(json.loads, self.log.read_text().splitlines()) if c[0] == name]

    def test_local_toolkit_beats_old_path_and_preserves_old_build(self):
        stale = self.root / ".runtime/cuda"
        stale.mkdir()
        (stale / "CMakeCache.txt").write_text("old CUDA 12.4")
        cpu = self.root / ".runtime/cpu/bin/whisper-cli"
        cpu.parent.mkdir(parents=True)
        cpu.write_text("preserve CPU")
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        configure = self.calls("cmake")[0]
        self.assertIn("-DCMAKE_CUDA_COMPILER=" + str(self.local), configure)
        self.assertIn("-DCMAKE_CUDA_ARCHITECTURES=120", configure)
        backup, = (self.root / ".runtime").glob("cuda-previous.*")
        self.assertEqual((backup / "CMakeCache.txt").read_text(), "old CUDA 12.4")
        self.assertEqual(cpu.read_text(), "preserve CPU")
        self.assertEqual(self.run_build().returncode, 0)
        self.assertEqual(len(list((self.root / ".runtime").glob("cuda-previous.*"))), 1)

    def test_explicit_old_compiler_fails_before_source_or_build_mutation(self):
        result = self.run_build(CUDACXX=str(self.bin / "nvcc"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("12.8 or newer", result.stderr)
        self.assertEqual(self.calls("git"), [])
        self.assertEqual(self.calls("cmake"), [])
        self.assertFalse((self.root / ".runtime/cuda").exists())

    def test_explicit_cuda_home_and_host_compiler_with_spaces(self):
        toolkit = self.root / "chosen toolkit"
        self.tool(toolkit / "bin/nvcc")
        result = self.run_build(CUDA_HOME=str(toolkit), CUDAHOSTCXX="/compiler path/g++")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-DCMAKE_CUDA_COMPILER=" + str(toolkit / "bin/nvcc"), self.calls("cmake")[0])
        self.assertIn("-DCMAKE_CUDA_HOST_COMPILER=/compiler path/g++", self.calls("cmake")[0])
        self.assertIn("-ccbin=/compiler path/g++", self.calls("nvcc")[-1])

    def test_compile_only_explicit_targets_do_not_require_driver(self):
        result = self.run_build(SCRIBE_CUDA_ARCHITECTURES="86;120", SCRIBE_BUILD_ONLY="1", NO_GPU="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls("nvidia-smi"), [])
        self.assertIn("-DCMAKE_CUDA_ARCHITECTURES=86;120", self.calls("cmake")[0])

    def test_host_compiler_failure_stops_before_build(self):
        result = self.run_build(FAIL_HOST="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("host compiler check failed", result.stderr)
        self.assertEqual(self.calls("cmake"), [])

    def test_driver_failure_is_actionable(self):
        result = self.run_build(NO_GPU="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Check nvidia-smi", result.stderr)
        self.assertEqual(self.calls("cmake"), [])

    def test_cpu_build_does_not_query_cuda(self):
        result = self.run_build("cpu", NO_GPU="1", FAIL_HOST="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls("nvcc"), [])
        self.assertEqual(self.calls("nvidia-smi"), [])
        self.assertIn("-DGGML_CUDA=OFF", self.calls("cmake")[0])

    def test_data_home_keeps_desktop_setup_and_cli_engine_paths_at_source(self):
        # Fresh imports are required: CLI defaults capture paths at import time.
        shutil.copytree(APP / "scribe", self.root / "scribe", ignore=shutil.ignore_patterns("__pycache__"))
        self.tool(self.bin / "ffmpeg")
        (self.root / "scripts/install-model.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            "directory = Path(sys.argv[sys.argv.index('--directory') + 1])\n"
            "directory.mkdir(parents=True, exist_ok=True)\n"
            "(directory / ('ggml-' + sys.argv[1] + '.bin')).write_bytes(b'model fixture')\n")
        data = self.root / "separate model data"
        code = '''
import threading
from pathlib import Path
from scribe.core import Options
from scribe.desktop import PROFILES, readiness, setup_profile
from scribe.paths import ROOT, RESOURCE_ROOT

assert ROOT != RESOURCE_ROOT
profile = PROFILES["laptop"]
for device, mode in (("cpu", "cpu"), ("gpu", "cuda")):
    # Run the real setup orchestration and build script with compiler/model
    # fixtures. The builder determines its directory from its own location.
    setup_profile(profile, threading.Event(), lambda _: None, device=device)
    assert readiness(profile, device=device) == []
    expected = RESOURCE_ROOT / ".runtime" / mode / "bin/whisper-cli"
    assert expected.is_file()
    desktop = profile.options(Path.cwd(), device=device)
    cli_defaults = Options(desktop.model, Path.cwd())
    field = "cpu_engine" if device == "cpu" else "gpu_engine"
    assert getattr(desktop, field) == expected
    assert getattr(cli_defaults, field) == expected
    assert desktop.model.parent == ROOT / "models"
    assert desktop.model.is_file()
assert not (ROOT / ".runtime").exists()
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=self.root,
                                env={**self.env, "SCRIBE_DATA_HOME": str(data), "PYTHONPATH": str(self.root)},
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("cuda_installer", APP / "scripts/install-cuda.py")
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.destination = Path(self.temp.name) / "toolkit"

    def archive(self, path="component/bin/nvcc"):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:xz") as bundle:
            entry = tarfile.TarInfo(path)
            entry.size, entry.mode = 7, 0o755
            bundle.addfile(entry, io.BytesIO(b"fixture"))
        return stream.getvalue()

    def install(self, data, digest):
        components = {"fixture": {"relative_path": "fixture.tar.xz", "sha256": digest}}
        with mock.patch.object(self.installer, "COMPONENTS", components), \
                mock.patch.object(self.installer.platform, "machine", return_value="x86_64"), \
                mock.patch.object(self.installer.urllib.request, "urlopen", return_value=io.BytesIO(data)):
            self.installer.install(self.destination)

    def test_verified_install_is_executable(self):
        data = self.archive()
        self.install(data, hashlib.sha256(data).hexdigest())
        self.assertTrue(os.access(self.destination / "bin/nvcc", os.X_OK))
        self.assertTrue((self.destination / "scribe-toolkit.json").is_file())

    def test_bad_digest_leaves_no_partial_install(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.install(self.archive(), "0" * 64)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_archive_cannot_write_outside_staging_directory(self):
        data = self.archive("../../escaped")
        with self.assertRaises(tarfile.FilterError):
            self.install(data, hashlib.sha256(data).hexdigest())
        self.assertFalse(self.destination.exists())
        self.assertFalse((self.destination.parent / "escaped").exists())

    def test_existing_unmanaged_toolkit_is_preserved(self):
        self.destination.mkdir()
        sentinel = self.destination / "keep"
        sentinel.write_text("existing")
        with self.assertRaisesRegex(ValueError, "move it aside"):
            self.install(b"", "0" * 64)
        self.assertEqual(sentinel.read_text(), "existing")


if __name__ == "__main__":
    unittest.main()
