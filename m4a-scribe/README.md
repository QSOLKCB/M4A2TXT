# M4A2TXT

**Local audio in. Plain text out.** An Ubuntu-first desktop app and batch CLI for transcribing NotebookLM Audio Overview exports and other audio files with Whisper.

Version: **0.3.0-preview**. The Linux package includes an executable `./m4a2txt` launcher at its top level. It uses native system dependencies and builds its engine on first-time setup; it is not a self-contained binary. See [VALIDATION.md](VALIDATION.md) for exactly what was exercised.

## What it does

- Select one or several `.m4a` files and save a separate UTF-8 `.txt` for each.
- Run Whisper locally on CPU, or request the CUDA engine for an NVIDIA GPU.
- Use a GTK 4 / libadwaita window with three machine presets, drag-and-drop, a queue, progress, transcript preview, and local playback.
- Cancel a batch without publishing the active job's unfinished transcript. Earlier completed files stay saved.
- Preserve existing outputs: `episode.txt`, then `episode (2).txt`, and so on.
- Also accept MP3, WAV, FLAC, AAC, OGG, OPUS, and the first audio stream of MP4.

The application starts no HTTP server and exposes no web or chat API. It calls local executables through child processes. There are no Python packages to install with pip, no JavaScript runtime, no account, no subscription, and no cloud inference. GTK and its Python bindings are supplied by the operating system.

Engine and model installation is a separate, explicit setup action, available from the GUI or the setup commands. **Once setup is complete, normal transcription needs no network connection.** A model can also be copied from another machine.

## Transcription policy

The app copies the recognizer's `.txt` bytes without rewriting them. It adds no summaries, speaker names, promotional lines, explanations, factual corrections, or profanity filtering. For example, a host saying an incorrect calculation must not trigger a second AI pass to repair it.

Whisper starts decoding at temperature zero and can retry uncertain or repetitive segments using its standard temperature fallback. These retries run on the selected processor; they do not enable CPU fallback for GPU mode or rewrite the transcript afterward. Text context is reset between audio windows to keep a bad prediction from repeating across the rest of a recording. This can reduce consistency of names between windows.

Whisper itself is not a guarantee of verbatim transcription. It can omit fillers, mishear names or numbers, repeat text, or hallucinate during silence. “No cleanup” describes what this app does after recognition; it does not remove those model limitations. Check important passages against the source audio.

The three-preset desktop transcribes English. The CLI also accepts another supported Whisper language code or `auto`. The task is transcription, not translation. VAD and automatic speaker labelling are not enabled in this preview.

## Three machine presets

| Preset | Local model | Approximate model download | CPU thread cap |
| --- | --- | --- | --- |
| **Laptop** | `small.en` | 466 MiB | 4 |
| **Mid** | `large-v3-turbo-q5_0` | 547 MiB | 4 |
| **High** | `large-v3` | 2.9 GiB | 8 |

Choose a preset, then use the **CPU / GPU** toggle below it. All three presets support either processor. **Mid + GPU** uses quantized turbo weights on NVIDIA CUDA; **High + GPU** uses full large-v3 weights on NVIDIA CUDA. CPU mode uses the same chosen model with GPU execution disabled. Laptop + CPU is the initial default. The app remembers the preset, processor, and output folder independently; changing the preset keeps your processor choice. Existing settings without a processor choice start on CPU.

These are download sizes, not VRAM requirements or measured speed/accuracy guarantees. Mid uses quantized weights to reduce model memory. High uses the larger unquantized model; it is not a promise that every word will be more accurate. GPU mode stops on failure and keeps the job available for retry. Choose CPU explicitly, or try Mid if High exhausts GPU memory. No smaller model is silently substituted.

The engine is [whisper.cpp v1.9.5](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5), pinned to `d1be6fde11ac6e0407606b4e42fe72d34add8037`. It uses local GGML `.bin` weights. The original `large-v3-turbo` and `tiny.en` setup options remain available for CLI use and smoke tests.

## Ubuntu setup

On Ubuntu 24.04 or newer, open a terminal in the repository’s `m4a-scribe` folder. Install the native system packages once:

```sh
sudo apt update
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 ffmpeg git cmake build-essential
```

Start the desktop:

```sh
sh run-scribe.sh
```

Select **Laptop**, **Mid**, or **High**, then **CPU** or **GPU**. If that combination needs an engine or model, the main button reads **Set up CPU/GPU**, with the preset and model download size shown above it. Clicking it explicitly downloads the model and builds the selected missing engine; it never uploads audio or starts transcription automatically. Once ready, add or drop audio files and click **Transcribe**. No network access is needed for that step.

All six preset/processor combinations show setup progress at the bottom of the window: engine-build percentages, model download bytes and percentages when the total is known, and an animated bar during preparation or verification. A spinner and elapsed time remain visible when a build step takes a while. Click **See Details For Log** to open the live setup output. Percentages apply to the current stage; a 100% download still needs checksum verification before setup completes. The display tracks setup started in the app; separately started terminal commands print their own progress. Whisper's existing transcription progress is unchanged.

The launcher uses `/usr/bin/python3`, so an activated virtual environment does not hide Ubuntu's GTK bindings. Set `SCRIBE_PYTHON` only when using another interpreter that already has the GI bindings. The desktop requires GTK 4.10+ and libadwaita 1.4+.

NVIDIA acceleration needs a compatible driver and CUDA toolkit. With GPU selected, setup requires a compatible `nvcc` to build the CUDA engine. The build checks GPU targets and host compiler compatibility before compiling. Missing compilers and failed builds are reported in Details; setup does not silently succeed using CPU. Existing CPU engines are retained, and CPU can be selected at any time while idle. Once a CUDA engine is installed, `nvcc` is not needed for transcription, but its CUDA runtime libraries and a compatible driver are. System packages and drivers are never installed or modified by the GUI.

### Manual or offline setup

The setup scripts are still available. For CPU mode:

```sh
sh scripts/build-engine.sh cpu
```

The build downloads the pinned upstream source, then compiles only `whisper-cli`. The server, model URL fetching, and RPC backend are disabled. The default build uses four compilation jobs; set `SCRIBE_BUILD_JOBS` to change that.

For the Laptop preset, install its model explicitly:

```sh
python3 scripts/install-model.py small.en --download
```

For Mid or High respectively:

```sh
python3 scripts/install-model.py large-v3-turbo-q5_0 --download
python3 scripts/install-model.py large-v3 --download
```

The installer checks the downloaded bytes against the file digest published in the pinned upstream model list and records a local SHA-256 checksum. Upstream's published digest in this list is SHA-1; the extra SHA-256 records the installed file and is not a publisher signature. The model URL can redirect to Hugging Face's download storage. This setup operation never receives your audio.

To import a model without downloading:

```sh
python3 scripts/install-model.py small.en \
  --from-file /path/to/ggml-small.en.bin
```

For GPU mode, first verify that `nvidia-smi` works. On Linux x86_64, install the optional project-local toolkit from the **repository or package root**, then build the CUDA engine (a CPU build is not required):

```sh
./install-deps.sh --cuda
sh m4a-scribe/scripts/build-engine.sh cuda
```

`--cuda` downloads about 842 MiB of pinned NVIDIA CUDA 13.2 components, verifies their SHA-256 digests, and installs them into `m4a-scribe/.runtime/toolkit`. Allow about 5 GiB of free space during installation. It uses no sudo and changes no system packages, drivers, apt repositories, or shell profiles. Run `./install-deps.sh` separately if native desktop dependencies are missing. Interrupted downloads leave no active partial toolkit; rerun the command to retry. Keep the toolkit alongside the engine: its libraries are also needed for transcription.

This path fixes the RTX 5060 Ti failure on Ubuntu 26.04: the distro's `/usr/bin/nvcc` reports CUDA 12.4, which rejects the pinned engine's `compute_120a` target. CUDA 13.2 supports both Blackwell and this machine's GCC 15 / glibc 2.42 toolchain. A working NVIDIA driver is still required; the installer never replaces one.

The build selects `CUDACXX`, then `CUDA_HOME/bin/nvcc`, then the project-local toolkit, PATH, and finally `/usr/local/cuda/bin/nvcc`. Explicit overrides take priority even if incompatible. GUI setup uses the same discovery without needing PATH changes. When the compiler or target configuration changes, the previous CUDA build is retained in `.runtime/cuda-previous.*` and a fresh build is configured. The CPU build and models are preserved.

The build script checks the selected compiler's supported targets and compiles a small CUDA source file before building the engine; it does not download a toolkit or change GPU drivers. RTX 50-series cards, including the RTX 5060 Ti, need CUDA 12.8 or newer for the native Blackwell build. Use an NVIDIA toolkit that supports your operating system and host compiler; see [NVIDIA's installation guide](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/). Check `nvcc --version`; the CUDA version shown by `nvidia-smi` is the driver's supported version, not proof that the compiler is installed. For a custom toolkit, set `CUDACXX=/path/to/bin/nvcc` or `CUDA_HOME=/path/to/toolkit`. Set `CUDAHOSTCXX` if that toolkit needs a different supported host compiler. For cross-compilation only, `SCRIBE_CUDA_ARCHITECTURES='86;120' sh scripts/build-engine.sh cuda` overrides native GPU detection; normal local setup targets the installed GPU. CPU and CUDA engines stay in separate directories.

Start the desktop app:

```sh
sh run-scribe.sh
```

Choose the machine preset and processor, add or drop audio files, and click **Transcribe**. Change the output folder only if needed. Completed jobs show CPU or the selected CUDA backend, such as **GPU (CUDA0)**, and offer **View** and **Copy text**, plus local playback through `ffplay`. **Open transcript folder** opens the saved files. Adding more audio does not retranscribe completed queue entries. Failed or cancelled entries can be retried. Closing during a job cancels it and waits for cleanup.

## CLI processor modes

| Mode | Behaviour |
| --- | --- |
| Auto | Try the CUDA executable when installed; otherwise use CPU. If the CUDA attempt fails, retry once from the beginning using the same model on the CPU executable. Report the fallback in Details. |
| GPU | Require a CUDA backend report from the pinned engine; stop on initialization failure or missing evidence, with no CPU retry. |
| CPU | Run the CPU executable with GPU use disabled. |

GPU mode monitors the pinned engine's initialization diagnostics throughout the process, including logs longer than the displayed diagnostic tail. A CUDA-enabled binary alone is insufficient: the app requires a `whisper_backend_init_gpu: using CUDA… backend` report and rejects explicit initialization failures. This confirms CUDA backend selection; decoding, orchestration, and some engine operations still use CPU. It is not a per-kernel profiler or a performance benchmark. The desktop exposes CPU/GPU; automatic CPU fallback remains available only through CLI `--device auto`.

## CUDA validation workflow

The repository's `CUDA engine checks` workflow builds the pinned engine with CUDA 12.8 for Ampere (`86`) and Blackwell (`120`) on a standard Ubuntu GitHub runner. It installs compilation tools only, with no NVIDIA driver installation, Docker, or inference service. A successful compile is not a GPU hardware test.

Its optional **hardware** input runs only when manually dispatched. It needs a registered self-hosted runner labelled `self-hosted`, `linux`, `x64`, `cuda`, with NVIDIA driver, CUDA toolkit, FFmpeg, Python 3.11+, CMake, Git and a C++ compiler already available. Use a trusted checkout on that runner. The job explicitly downloads both Mid and High models (about 3.5 GiB total), processes the pinned public JFK sample on each model, and uploads the public sample transcripts and a receipt containing model/engine/output hashes, backend reports, and elapsed times. It never selects personal audio. The hardware job is not automatically run for pull requests.

After setting up Mid + GPU and High + GPU locally, run the same check without downloads:

```sh
python3 scripts/check-cuda.py --preset mid --preset high --output-dir /path/to/new-cuda-check
```

The output folder must be new. Use just `--preset mid` to check the smaller model first. A successful receipt requires a nonempty transcript and a CUDA backend report for each requested preset. A local High + GPU full-recording run on an RTX 5060 Ti is recorded in [VALIDATION.md](VALIDATION.md); this two-preset public-sample check remains available for other installations.

## Batch command line

From the project folder:

```sh
python3 -m scribe \
  --model models/ggml-small.en.bin \
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

The GUI remembers only the selected preset, CPU/GPU choice, and output directory in the user's XDG configuration directory (`~/.config/m4a-scribe/settings.json` by default). It keeps no persistent transcript database or audio history. The output folder contains the `.txt` files you chose to create. Runtime log content stays in the current window or temporary storage.

## Tests

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q scribe scripts tests
```

Pipeline tests perform real FFmpeg encoding/decoding and deliberately substitute a tiny fake executable for Whisper. They test error handling, argument boundaries, output preservation, cancellation, and fallback. They do not measure ASR accuracy. See [VALIDATION.md](VALIDATION.md) for separate real-engine results and remaining checks. `tests/gtk_smoke.py` exercises real GTK widgets under Xvfb using a controlled recognizer; it does not download models or transcribe private audio.

## Project layout

| Path | Purpose |
| --- | --- |
| `scribe/core.py` | Local process supervision, decoding, cancellation, output publication |
| `scribe/gui.py` | Native GTK desktop window and local playback |
| `scribe/desktop.py` | Three presets, setup, settings, and batch state |
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

- [NVIDIA CUDA 13.2 host compiler and Linux requirements](https://docs.nvidia.com/cuda/archive/13.2.0/cuda-installation-guide-linux/index.html)
- [Pinned NVIDIA CUDA 13.2 component manifest](https://developer.download.nvidia.com/compute/cuda/redist/redistrib_13.2.0.json)
