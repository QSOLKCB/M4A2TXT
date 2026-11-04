"""Task, output, PCM reuse and cross-platform process regressions."""
from dataclasses import replace
import io
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock
import wave

from scribe.core import Options, ScribeError, prepare_audio, publish_text, run_process, transcribe, validate_model_task
from scribe.desktop import Settings, selected_profile


class QualityOfLifeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'model.bin'
        self.model.write_bytes(b'controlled adapter fixture')
        self.source = self.root / 'speech.wav'
        with wave.open(str(self.source), 'wb') as out:
            out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            out.writeframes(b'\x01\x02' * 1600)
        self.engine = self.root / 'engine'
        self.engine.write_text('fixture')
        self.engine.chmod(0o755)
        self.output = self.root / 'output'
        self.output.mkdir()
        self.options = Options(self.model, self.output, device='cpu', cpu_engine=self.engine)

    def test_pcm_snapshot_reused_without_decoder_and_without_byte_changes(self):
        events = []
        with mock.patch('scribe.core.decode_audio') as decode:
            result = prepare_audio(self.source, self.root / 'decoded.wav', self.options, threading.Event(), events.append)
        self.assertEqual(result, self.source)
        decode.assert_not_called()
        self.assertEqual(result.read_bytes(), self.source.read_bytes())
        self.assertIn('directly', events[-1])

    def test_other_pcm_format_still_decoded(self):
        with wave.open(str(self.source), 'wb') as out:
            out.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
            out.writeframes(b'\x00' * 400)
        with mock.patch('scribe.core.decode_audio') as decode:
            result = prepare_audio(self.source, self.root / 'decoded.wav', self.options, threading.Event(), lambda _: None)
        decode.assert_called_once()
        self.assertEqual(result.name, 'decoded.wav')

    def test_progress_callback_runtime_error_is_not_treated_as_bad_wav(self):
        def broken_callback(_message):
            raise RuntimeError('callback fixture')
        with mock.patch('scribe.core.decode_audio') as decode:
            with self.assertRaisesRegex(RuntimeError, 'callback fixture'):
                prepare_audio(self.source, self.root / 'decoded.wav', self.options,
                              threading.Event(), broken_callback)
        decode.assert_not_called()

    def test_truncated_and_overlong_pcm_do_not_reach_engine(self):
        original = self.source.read_bytes()
        self.source.write_bytes(original[:-2])
        with self.assertRaisesRegex(ScribeError, 'truncated'):
            prepare_audio(self.source, self.root / 'decoded.wav', self.options, threading.Event(), lambda _: None)
        self.source.write_bytes(original)
        with self.assertRaisesRegex(ScribeError, 'duration'):
            prepare_audio(self.source, self.root / 'decoded.wav', replace(self.options, max_seconds=.01), threading.Event(), lambda _: None)

    def test_translation_and_subtitles_preserve_engine_bytes_and_do_not_overwrite(self):
        for fmt, data in (('txt', b'Hello.\n'), ('srt', b'1\n00:00:00,000 --> 00:00:00,100\nHello.\n'),
                          ('vtt', b'WEBVTT\n\n00:00:00.000 --> 00:00:00.100\nHello.\n')):
            options = replace(self.options, task='translate', language='fr', output_format=fmt)
            calls = []
            def recognize(argv, *_args, **_kwargs):
                calls.append(argv)
                self.assertIn('--translate', argv)
                self.assertIn('--output-' + fmt, argv)
                prefix = argv[argv.index('--output-file') + 1]
                Path(prefix + '.' + fmt).write_bytes(data)
            with mock.patch('scribe.core.run_process', side_effect=recognize):
                first = transcribe(self.source, options)
                second = transcribe(self.source, options)
            self.assertEqual(first.output.name, 'speech.en.' + fmt)
            self.assertEqual(second.output.name, 'speech.en (2).' + fmt)
            self.assertEqual(first.output.read_bytes(), data)
            self.assertEqual(second.output.read_bytes(), data)
            self.assertEqual(len(calls), 2)

    def test_missing_subtitle_output_fails_without_publication(self):
        with mock.patch('scribe.core.run_process'):
            with self.assertRaisesRegex(ScribeError, 'without producing'):
                transcribe(self.source, replace(self.options, output_format='srt'))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_renamed_english_and_turbo_headers_rejected_before_decode(self):
        for vocab, audio_layers, text_layers, mel in ((51864, 4, 4, 80), (51866, 32, 4, 128)):
            self.model.write_bytes(struct.pack('<12i', 0x67676D6C, vocab, 1500, 384, 6, audio_layers, 448, 384, 6, text_layers, mel, 1))
            with self.assertRaises(ScribeError), mock.patch('scribe.core.prepare_audio') as prepare:
                transcribe(self.source, replace(self.options, task='translate'))
            prepare.assert_not_called()
        self.model.write_bytes(struct.pack('<12i', 0x67676D6C, 51866, 1500, 1280, 20, 32, 448, 1280, 20, 32, 128, 1))
        validate_model_task(self.model, replace(self.options, task='translate'))

    def test_translation_presets_choose_compatible_models(self):
        self.assertEqual(selected_profile('laptop').model, 'small.en')
        self.assertEqual(selected_profile('laptop', language='auto').model, 'small')
        self.assertEqual(selected_profile('mid').model, 'large-v3-turbo-q5_0')
        self.assertEqual(selected_profile('mid', task='translate').model, 'small')
        self.assertEqual(selected_profile('high', task='translate').model, 'large-v3')

    def test_settings_roundtrip_new_fields_and_reject_malformed_values(self):
        path = self.root / 'settings.json'
        settings = Settings(path)
        settings.task, settings.language, settings.output_format, settings.large_text = 'translate', 'fr', 'vtt', True
        settings.save()
        loaded = Settings(path)
        self.assertEqual((loaded.task, loaded.language, loaded.output_format, loaded.large_text), ('translate', 'fr', 'vtt', True))
        path.write_text('{"task": [], "language": [], "output_format": {}, "large_text": "true"}')
        loaded = Settings(path)
        self.assertEqual((loaded.task, loaded.language, loaded.output_format, loaded.large_text), ('transcribe', 'en', 'txt', False))

    def test_live_process_output_does_not_depend_on_pread(self):
        events, observed = [], bytearray()
        code = "import time; print('progress = 42%', flush=True); time.sleep(.3); print('finished', flush=True)"
        with mock.patch('scribe.core.os.pread', side_effect=AssertionError('pread must not be used'), create=True):
            output = run_process([sys.executable, '-c', code], self.root, threading.Event(), events.append, 'Whisper', observer=observed.extend)
        self.assertIn('Whisper: 42%', events)
        self.assertEqual(observed, output.encode())
        self.assertEqual(list(self.root.glob('process-*')), [])

    def test_bad_output_format_cannot_escape_destination(self):
        with self.assertRaises(ScribeError):
            publish_text(self.source, self.output, 'name', threading.Event(), '../bad')


if __name__ == '__main__':
    unittest.main()
