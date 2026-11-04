#!/usr/bin/env python3
"""Validate the extracted native artifact, not the source checkout's runtime."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(args, **kwargs):
    completed = subprocess.run([str(value) for value in args], capture_output=True, text=True, timeout=240, **kwargs)
    if completed.returncode:
        raise RuntimeError(f'{args}: exit {completed.returncode}\n{completed.stdout}\n{completed.stderr}')
    return completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    archives = list(args.dist.glob('*-portable.zip')) + list(args.dist.glob('*-portable.tar.gz'))
    if len(archives) != 1:
        raise RuntimeError('Expected exactly one native archive')
    archive = archives[0]
    expected = archive.with_name(archive.name + '.sha256').read_text().split()[0]
    assert digest(archive) == expected
    records = []
    with tempfile.TemporaryDirectory(prefix='m4a2txt extracted package ') as temporary:
        work = Path(temporary)
        if archive.suffix == '.zip':
            with zipfile.ZipFile(archive) as package:
                package.extractall(work)
        else:
            with tarfile.open(archive) as package:
                package.extractall(work, filter='data')
        payload, = work.iterdir()
        receipt = json.loads((payload / 'BUILD-RECEIPT.json').read_text())
        for name, expected in receipt['files'].items():
            assert digest(payload / name) == expected, name
        executable = payload / ('M4A2TXT.app/Contents/MacOS/M4A2TXT' if sys.platform == 'darwin' else 'M4A2TXT/M4A2TXT.exe' if os.name == 'nt' else 'M4A2TXT/M4A2TXT')
        run([executable, '--version'])
        run([executable, '--cli', '--help'])
        if sys.platform in {'win32', 'darwin'}:
            run([executable, '--check'])
        models = work / 'local models'
        # The explicit installer hashes a cached model again before use.
        cache = ROOT / '.portable-build/test-models'
        cache.mkdir(parents=True, exist_ok=True)
        run([executable, '--install-model', 'tiny.en', '--download', '--directory', cache])
        run([executable, '--install-model', 'tiny.en', '--from-file', cache / 'ggml-tiny.en.bin', '--directory', models])
        sample = ROOT / '.portable-build/whisper-source/samples/jfk.wav'
        output = work / 'output'
        output.mkdir()
        environment = os.environ.copy()
        environment['PATH'] = ''  # No host Python, FFmpeg or Whisper can rescue this package.
        environment['HTTP_PROXY'] = environment['HTTPS_PROXY'] = 'http://127.0.0.1:9'
        for fmt in ('txt', 'srt', 'vtt'):
            completed = run([executable, '--cli', '--model', models / 'ggml-tiny.en.bin', '--device', 'cpu',
                             '--output-dir', output, '--output-format', fmt, sample], env=environment, cwd=work)
            target = output / ('jfk.' + fmt)
            text = target.read_text(encoding='utf-8').lower()
            assert 'country' in text, (fmt, text)
            if fmt != 'txt':
                assert '-->' in text
            records.append({'format': fmt, 'sha256': digest(target), 'recognition': 'country found in public JFK sample'})
        compressed = work / 'decoder.m4a'
        compressed.write_bytes(base64.b64decode(M4A_FIXTURE))
        run([executable, '--cli', '--model', models / 'ggml-tiny.en.bin', '--device', 'cpu',
             '--output-dir', output, compressed], env=environment, cwd=work)
        assert (output / 'decoder.txt').is_file()
        records.append({'m4a_decode': 'passed with bundled FFmpeg and empty PATH'})
    (args.dist / 'portable-validation.json').write_text(json.dumps({'archive_sha256': digest(archive), 'records': records}, indent=2) + '\n')
    print('Portable package PASS: extraction, manifests, explicit model installation, real TXT/SRT/VTT recognition, M4A decode, empty PATH')


# Generated 0.25-second sine/AAC fixture, not speech or private user audio.
M4A_FIXTURE = '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'

if __name__ == '__main__':
    main()
