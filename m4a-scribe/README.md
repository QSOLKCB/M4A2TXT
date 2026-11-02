# M4A Scribe

**Local audio in. Plain text out.** An Ubuntu-first desktop app and batch CLI for transcribing NotebookLM Audio Overview exports and other audio files with Whisper.

Version: **0.1.0-preview**. This is a source starter, not a prebuilt desktop release. See [VALIDATION.md](VALIDATION.md) for exactly what was exercised.

## What it does

- Select one or several `.m4a` files and save a separate UTF-8 `.txt` for each.
- Run Whisper locally on CPU, or request the CUDA engine for an NVIDIA GPU.
- Use a small native window with a queue, progress, read-only transcript preview, and local playback.
- Cancel a batch without publishing the active job's unfinished transcript. Earlier completed files stay saved.
- Preserve existing outputs: `episode.txt`, then `episode (2).txt`, and so on.
- Also accept MP3, WAV, FLAC, AAC, OGG, OPUS, and the first audio stream of MP4.

The application starts no HTTP server and exposes no web or chat API. It calls local executables through child processes. There are no Python packages to install with pip, no JavaScript runtime, no account, no subscription, and no cloud inference. Python's Tk interface is supplied by the operating system.

Engine and model installation are separate setup commands. **Once setup is complete, normal transcription needs no network connection.** A model can also be copied from another machine.

## Transcription policy

The app copies the recognizer's `.txt` bytes without rewriting them. It adds no summaries, speaker names, promotional lines, explanations, factual corrections, or profanity filtering. For example, a host saying an incorrect calculation must not trigger a second AI pass to repair it.

Whisper itself is not a guarantee of verbatim transcription. It can omit fillers, mishear names or numbers, repeat text, or hallucinate during silence. “No cleanup” describes what this app does after recognition; it does not remove those model limitations. Check important passages against the source audio.

English is the default language. Enter another supported Whisper language code or `auto` in the language field. The task is transcription, not translation. VAD and automatic speaker labelling are not enabled in this preview.

## Model choice

| Model | Approximate model file | Suggested use |
| --- | --- | --- |
| `large-v3-turbo` | 1.5 GiB | Starting choice for clean Audio Overviews on a capable GPU |
| `large-v3` | 2.9 GiB | Comparison model when accuracy matters more than turnaround |
| `small.en` | 466 MiB | Lighter English-only option for CPU use |
| `tiny.en` | 75 MiB | Installation smoke tests; not the recommended research transcript model |

These are upstream file sizes, not VRAM requirements or speed promises. Compare the first two on representative episodes before making claims about which is more accurate for this material. The same model can run on CPU; the application never silently selects a smaller model.

The main engine is [whisper.cpp v1.9.5](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5), pinned to commit `d1be6fde11ac6e0407606b4e42fe72d34add8037`. The app uses local GGML `.bin` weights, not a PyTorch `.pt` file or a Hugging Face repository name.

## Ubuntu setup

Extract the archive and open a terminal in the `m4a-scribe` folder. Install system prerequisites:

```sh
sudo apt update
sudo apt install python3 python3-tk ffmpeg git cmake build-essential
```

Build the CPU engine first:

```sh
sh scripts/build-engine.sh cpu
```

The build downloads the pinned upstream source, then compiles only `whisper-cli`. The server, model URL fetching, and RPC backend are disabled. The default build uses four compilation jobs; set `SCRIBE_BUILD_JOBS` to change that.

Install the recommended starting model explicitly:

```sh
python3 scripts/install-model.py large-v3-turbo --download
```

For a lighter CPU model instead:

```sh
python3 scripts/install-model.py small.en --download
```

The installer checks the downloaded bytes against the file digest published in the pinned upstream model list and records a local SHA-256 checksum. Upstream's published digest in this list is SHA-1; the extra SHA-256 records the installed file and is not a publisher signature. The model URL can redirect to Hugging Face's download storage. This setup operation never receives your audio.

To import a model without downloading:

```sh
python3 scripts/install-model.py large-v3-turbo \
  --from-file /path/to/ggml-large-v3-turbo.bin
```

For NVIDIA acceleration, install a compatible NVIDIA driver and CUDA toolkit using the appropriate packages for your machine, then build the second engine:

```sh
sh scripts/build-engine.sh cuda
```

The script checks for `nvcc`; it does not install or change GPU drivers. Newer GPUs, including the RTX 50 series, need a CUDA toolkit that supports their architecture. Keep the CPU build as the independent fallback.

Start the desktop app:

```sh
sh run-scribe.sh
```

Choose audio files, check the model and output folder, then click **Transcribe**. The model selector automatically finds the default model in `models/` after installation. Playback uses local `ffplay` when available. This preview uses a file picker; drag-and-drop is not implemented.

## Processor modes

| Mode | Behaviour |
| --- | --- |
| Auto | Try the CUDA executable when installed; otherwise use CPU. If the CUDA attempt fails, retry once from the beginning using the same model on the CPU executable. Report the fallback in Details. |
| GPU preferred | Run the CUDA executable only; do not retry with the separate CPU executable. |
| CPU | Run the CPU executable with GPU use disabled. |

“GPU preferred” is deliberate: whisper.cpp manages backend selection internally. This wrapper does not yet prove that every operation ran on the GPU. A successful CUDA process is not reported as a measured GPU benchmark. Actual device reporting is a planned follow-up.

## Batch command line

From the project folder:

```sh
python3 -m scribe \
  --model models/ggml-large-v3-turbo.bin \
  --device auto \
  --output-dir /path/to/transcripts \
  /path/to/episode-a.m4a /path/to/episode-b.m4a
```

Quote paths containing spaces. The output folder must already exist. The output contains no timestamps or metadata. Diagnostics go to stderr; saved output paths go to stdout. Ctrl+C cancels the active job and remaining queue. Exit codes: `0` for all files completed, `1` for a file failure, `2` for usage/setup errors, `130` for cancellation. A zero-byte transcript means the recognizer returned no text and is explicitly reported.

Use `--language en`, `--language auto`, or another Whisper language code. Use `--threads 8` to set CPU threads. Custom local executables can be selected with `--cpu-engine /path/to/whisper-cli` and `--gpu-engine /path/to/whisper-cli`; those executables are trusted local dependencies.

## Local data and boundaries

Audio is copied to a private temporary directory before decoding, so the recognizer processes a stable copy. The original is not modified. FFmpeg converts it to mono, 16 kHz, signed 16-bit PCM and is restricted to local file/pipe protocols and a format-specific demuxer. The conversion does not intentionally denoise, trim silences, adjust loudness, or remove speech.

The preview accepts regular local files up to 4 GiB and decoded audio up to four hours. It rejects excess duration rather than returning a silently truncated transcript. Source symlinks and special files such as FIFOs are rejected; select the real audio file. Temporary audio and partial output are removed on ordinary completion, failure, or cancellation. A forced crash or power loss can leave temporary files; this is not secure erasure.

Publishing uses an atomic, no-overwrite hard link on the destination filesystem. Use a local filesystem with hard-link support, such as ext4. FAT/exFAT output volumes are not supported by this preview; export to a local folder and copy the finished transcript to those volumes afterward.

The GUI remembers only the model path, output directory, processor choice, and language in the user's XDG configuration directory (`~/.config/m4a-scribe/settings.json` by default). It keeps no persistent transcript database or audio history. The output folder contains the `.txt` files you chose to create. Runtime log content stays in the current window or temporary storage.

## Tests

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q scribe scripts tests
```

Pipeline tests perform real FFmpeg encoding/decoding and deliberately substitute a tiny fake executable for Whisper. They test error handling, argument boundaries, output preservation, cancellation, and fallback. They do not measure ASR accuracy. See [VALIDATION.md](VALIDATION.md) for separate real-engine results and remaining checks.

## Project layout

| Path | Purpose |
| --- | --- |
| `scribe/core.py` | Local process supervision, decoding, cancellation, output publication |
| `scribe/gui.py` | Native Tk desktop window and local playback |
| `scribe/__main__.py` | CLI and GUI entry point |
| `scripts/build-engine.sh` | Explicit pinned engine setup |
| `scripts/install-model.py` | Explicit model download or offline import |
| `tests/test_pipeline.py` | Local pipeline regression checks |
| `DESIGN.md` | Architecture, decisions, and implementation stages |

App source: MIT. Whisper model weights and whisper.cpp have their own upstream notices. FFmpeg licensing depends on the installed build; it is a system dependency here, not redistributed in this archive.

## Primary references

- [whisper.cpp source and backends](https://github.com/ggml-org/whisper.cpp/tree/d1be6fde11ac6e0407606b4e42fe72d34add8037)
- [Pinned model list and file sizes](https://github.com/ggml-org/whisper.cpp/blob/d1be6fde11ac6e0407606b4e42fe72d34add8037/models/README.md)
- [Whisper model card and limitations](https://github.com/openai/whisper/blob/main/model-card.md)
- [Whisper large-v3-turbo model card](https://huggingface.co/openai/whisper-large-v3-turbo)
- [FFmpeg protocol controls](https://ffmpeg.org/ffmpeg-protocols.html)
