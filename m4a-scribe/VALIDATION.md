# Validation

## GTK update 0.2.0 preview

- **28 local regression tests passed**, including the original 19 pipeline checks and nine desktop-state tests.
- Python syntax and both shell scripts passed their checks.
- The [GTK workflow passed](https://github.com/QSOLKCB/M4A2TXT/actions/runs/41537381909), exercising actual GTK widgets under Xvfb: all three presets, setup readiness, file dropping, queue completion, transcript viewing, file-dialog cancellation, and closing during work. It captures layouts using a controlled recognizer and downloads no models. The workflow also runs the 28 regression tests and syntax checks on Ubuntu 24.04. Later branch runs repeat these checks after changes.
- Local GUI rendering is unavailable because this workspace denies Unix sockets. Actual NVIDIA hardware inference and full-episode accuracy remain unverified.

## Retained 0.1.0 preview record

The remainder records the original source preview, not new GPU or GTK evidence.

Validation date: 3 November 2026. These checks were performed in the development workspace, not on the user's desktop.

## Executed

| Check | Result | Scope |
| --- | --- | --- |
| Python regression suite | 19 tests passed | Real FFmpeg encode/decode; fake recognizer used for controlled failure and output cases |
| Pinned whisper.cpp build | Passed | CPU build from `d1be6fde11ac6e0407606b4e42fe72d34add8037`, release configuration reports `1.9.5` |
| Model installer | Passed | Real `tiny.en` download; upstream file digest matched; local SHA-256 recorded |
| Corrupt model import | Passed | Offline import rejected mismatched bytes and left no installed model |
| Real M4A transcription | Passed | Upstream JFK speech sample encoded to AAC/M4A, then decoded and transcribed through the application on CPU |
| Runtime without socket access | Passed | Same real CLI pipeline under an inherited seccomp filter; IPv4, IPv6, and Unix socket creation explicitly verified denied before execution |
| Existing transcript preservation | Passed | Second real run created `jfk (2).txt`; the first `jfk.txt` remained intact |
| Python syntax, shell syntax, CLI help | Passed | All shipped Python modules compile; launch/build shell scripts parse; CLI/setup help executes |
| Headless launch error | Passed | GUI launch without a display returns an actionable setup message and exit code 2 |

The real recognizer returned a coherent transcript of the short speech sample. The two test outputs matched each other. This is evidence that the installed model, built engine, M4A adapter, and output path work together. It is not a measured word-error-rate study or a full-episode coverage test.

The structured record in [validation/cpu-smoke.json](validation/cpu-smoke.json) contains exact source, engine, model, and output hashes, settings, and observed text. [validation/pipeline-tests.txt](validation/pipeline-tests.txt) contains the regression result. The archive omits model weights, engine binaries, and the audio fixture; setup retrieves the engine/model separately.

The regression suite covers malformed/empty audio, FIFOs and source symlinks, Unicode and shell metacharacters in names, simultaneous output publication, existing output symlinks, bounded output filenames, decode-duration rejection, empty/missing recognizer output, GPU-attempt failure with explicit CPU retry, pre-cancellation, active-process cancellation, and decoder protocol restrictions.

## Not yet validated

- NVIDIA CUDA compilation or inference, actual GPU offload, VRAM use, and performance on the RTX 5060 Ti or other user hardware.
- Recognition quality with `large-v3-turbo`, `large-v3`, or `small.en`, or on the user's Audio Overviews.
- Long episodes, overlapping speakers, technical names, and exact recovery of fillers/hesitations.
- Native window layout, file dialogs, and playback in a real desktop session. The headless environment refused Xvfb's listening sockets, so the GUI was not visually exercised.
- A packaged clean-machine desktop installation, Windows, or macOS.
- Crash/power-loss recovery or hostile replacement executables. The network-denial harness is a test for the normal runtime, not a complete application sandbox.

These limits are why the bundle is labelled a source preview. CPU inference and the local workflow have executed successfully; the desktop and GPU path still need their respective acceptance runs.

## Repeat the offline smoke test on Linux

After building the CPU engine and installing a model, run the optional harness with a local audio file and existing output directory:

```sh
python3 tests/offline_smoke.py \
  --device cpu --threads 4 \
  --model models/ggml-tiny.en.bin \
  --output-dir /path/to/transcripts \
  /path/to/sample.m4a
```

The harness requires the OS `libseccomp` runtime. It applies its restrictions only to its own process and descendants, verifies they work, and then replaces itself with the CLI. It does not modify the system firewall or the normal app configuration.
