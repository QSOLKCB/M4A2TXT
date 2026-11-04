"""An engine cache must match the full toolchain identity and every payload byte."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('engine_cache', ROOT / 'scripts/cuda-cache-check.py')
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class EngineCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for key, path in [('APP', self.root / 'app'), ('EVIDENCE', self.root / 'evidence'), ('ENGINE_CACHE', self.root / 'cache')]:
            patch = mock.patch.object(cache, key, path)
            patch.start()
            self.addCleanup(patch.stop)
        cache.EVIDENCE.mkdir()
        (cache.EVIDENCE / 'toolchain.json').write_text('toolchain/configuration fixture')
        build = cache.APP / '.runtime/cuda'
        (build / 'bin').mkdir(parents=True)
        (build / 'bin/whisper-cli').write_bytes(b'ELF fixture')
        (build / 'bin/whisper-cli').chmod(0o755)
        (build / 'CMakeCache.txt').write_text('GGML_CUDA:BOOL=ON\n')
        cache.save_engine()

    def test_exact_cache_reuses_bytes(self):
        (cache.APP / '.runtime/cuda/bin/whisper-cli').unlink()
        self.assertTrue(cache.restore_engine())
        self.assertEqual((cache.APP / '.runtime/cuda/bin/whisper-cli').read_bytes(), b'ELF fixture')

    def test_corruption_missing_and_identity_change_are_rejected(self):
        for filename in ('whisper-cli', 'CMakeCache.txt', 'receipt.json'):
            target = cache.ENGINE_CACHE / filename
            original = target.read_bytes()
            target.write_bytes(b'corrupt')
            self.assertFalse(cache.restore_engine(), filename)
            target.unlink()
            self.assertFalse(cache.restore_engine(), filename)
            target.write_bytes(original)
            target.chmod(0o755)
        (cache.EVIDENCE / 'toolchain.json').write_text('different compiler or flags')
        self.assertFalse(cache.restore_engine())

    def test_unexpected_receipt_entries_and_symlinks_are_rejected(self):
        path = cache.ENGINE_CACHE / 'receipt.json'
        data = json.loads(path.read_text())
        data['files']['../outside'] = 'invalid'
        path.write_text(json.dumps(data))
        self.assertFalse(cache.restore_engine())
        cache.save_engine()
        target = cache.ENGINE_CACHE / 'whisper-cli'
        target.unlink()
        target.symlink_to(cache.APP / '.runtime/cuda/bin/whisper-cli')
        self.assertFalse(cache.restore_engine())
