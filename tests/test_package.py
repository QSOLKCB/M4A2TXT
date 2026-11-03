"""Check the package's actual contents, executable entry point, and reproducibility."""
import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("package_builder", ROOT / "scripts/package.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.repo = self.work / "source checkout"
        self.repo.mkdir()
        candidates = [ROOT / path for path in package.ROOT_FILES]
        candidates += list((ROOT / "m4a-scribe").rglob("*"))
        for source in candidates:
            if source.is_file() and package.selected(source.relative_to(ROOT).as_posix()):
                target = self.repo / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        # Even tracked user/runtime material must stay out of the package.
        for name in ("m4a-scribe/models/private.m4a", "m4a-scribe/.runtime/engine",
                     "m4a-scribe/transcript.txt", "archive/old.tar.gz"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"excluded fixture")
        self.git("init", "-q")
        self.git("add", "-f", ".")
        self.git("-c", "user.name=Package Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")

    def git(self, *args):
        return package.git(self.repo, *args)

    def test_roundtrip_reproducibility_manifest_and_launcher(self):
        first = package.build(self.repo, "HEAD", self.work / "build 1")
        # A working-tree change must not leak into a commit-addressed package.
        (self.repo / "m4a-scribe/scribe/__init__.py").write_text('__version__ = "9.9.9"\n')
        second = package.build(self.repo, "HEAD", self.work / "build 2")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(first.with_suffix(".gz.sha256").read_text().split()[0], hashlib.sha256(first.read_bytes()).hexdigest())
        extracted = self.work / "directory with spaces"
        with tarfile.open(first) as tar:
            self.assertTrue(all(item.isfile() or item.isdir() for item in tar.getmembers()))
            tar.extractall(extracted, filter="data")
        folder, = extracted.iterdir()
        for line in (folder / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest, name)
        self.assertEqual((folder / "SOURCE_COMMIT.txt").read_text().strip(), self.git("rev-parse", "HEAD").decode().strip())
        for name in ("m4a-scribe/models/private.m4a", "m4a-scribe/.runtime/engine", "m4a-scribe/transcript.txt", "archive"):
            self.assertFalse((folder / name).exists(), name)
        self.assertEqual((folder / "m4a2txt").stat().st_mode & 0o777, 0o755)
        for args, expected in ((["--version"], "0.3.0-preview"), (["--help"], "Usage: ./m4a2txt"),
                               (["--cli", "--help"], "--model")):
            run = subprocess.run([str(folder / "m4a2txt"), *args], cwd=self.work,
                                 capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn(expected, run.stdout)

    def test_non_executable_launcher_is_rejected(self):
        self.git("update-index", "--chmod=-x", "m4a2txt")
        self.git("-c", "user.name=Package Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "broken mode")
        with self.assertRaisesRegex(ValueError, "must be executable"):
            package.build(self.repo, "HEAD", self.work / "bad build")


if __name__ == "__main__":
    unittest.main()
