# Install M4A2TXT

M4A2TXT runs Whisper locally through a GTK desktop or a batch command line. Setup
installs native dependencies, builds an engine, and downloads the model you choose.
After setup, transcription works offline.

**Run the commands below from the repository root**: the folder containing
`m4a2txt` and `install-deps.sh`. The same setup commands work from the top of an
extracted Linux application package.

## Requirements

- Ubuntu 24.04 or newer for the supported desktop setup. Ubuntu 26.04.1 is covered
  by the project's [RTX 5060 Ti validation](m4a-scribe/VALIDATION.md).
- System Python, GTK 4.10+, libadwaita 1.4+, FFmpeg, Git, CMake, and a C++ compiler.
  The dependency helper installs these through Ubuntu's package manager.
- A writable application folder and internet access for initial setup.
- Space for the engine build and your chosen model. For the optional CUDA toolkit,
  allow about 5 GiB of free space during installation, in addition to the model
  and engine build.
- For GPU mode: an NVIDIA GPU with a working, compatible driver. The bundled
  toolkit installer supports Linux x86_64. CPU mode does not need CUDA or an
  NVIDIA driver.

There is no pip install or virtual environment to create. The desktop launcher
uses `/usr/bin/python3` so it can find Ubuntu's GTK bindings. The application
folder does not bundle Python, GTK, FFmpeg, model weights, or a prebuilt engine.

## 1. Get the application

For a source installation:

```sh
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/QSOLKCB/M4A2TXT.git
cd M4A2TXT
```

If you already cloned the repository, open a terminal in that folder and continue
with step 2.

Alternatively, download the `m4a2txt-linux` artifact from a successful
[Local app checks run](https://github.com/QSOLKCB/M4A2TXT/actions/workflows/tests.yml)
for the commit you want. Unzip the artifact, then run these commands in the folder
containing its `.tar.gz` and `.sha256` files:

```sh
sha256sum -c M4A2TXT-0.3.0-preview-linux.tar.gz.sha256
tar -xzf M4A2TXT-0.3.0-preview-linux.tar.gz
cd M4A2TXT-0.3.0-preview
sha256sum -c SHA256SUMS
```

Substitute the version in your downloaded filename if different. Packages include
`SOURCE_COMMIT.txt` to identify their source revision. Use a build containing the
latest CUDA fixes; the retained 0.2.0 archive predates both those fixes and the
CPU/GPU toggle. Keep the application folder together in a writable location.

## 2. Install native dependencies

```sh
./install-deps.sh
./m4a2txt --check
```

The helper uses `sudo apt-get` to install Python, GTK bindings, FFmpeg, Git, CMake,
and build tools. It does not build an engine, download a model, or install an
NVIDIA driver. Run the application and its engine/model setup as your normal user.

`--check` reports missing engines and models without downloading anything. A
message such as `set up model download` is expected before first-time setup.
The check can pass when desktop dependencies are ready even if no model is
installed. It does not prove GPU execution works.

## 3. Choose CPU or NVIDIA GPU

### CPU setup

```sh
./m4a2txt
```

Choose **Laptop**, **Mid**, or **High**, select **CPU**, and click **Set up CPU**.
The app builds the missing CPU engine and installs the selected model. Once setup
finishes, add audio and click **Transcribe**.

To set up Laptop + CPU entirely from the terminal instead:

```sh
sh m4a-scribe/scripts/build-engine.sh cpu
python3 m4a-scribe/scripts/install-model.py small.en --download
./m4a2txt
```

### NVIDIA GPU setup, including RTX 5060 Ti / RTX 50-series

First check that the NVIDIA driver can see your GPU:

```sh
nvidia-smi
```

If this fails in your normal desktop terminal, resolve the driver installation
before continuing with GPU setup. M4A2TXT's installers do not install or replace
drivers. You can use CPU mode in the meantime.

Install the project-local CUDA toolkit:

```sh
./install-deps.sh --cuda
```

This downloads about 842 MiB of pinned NVIDIA CUDA 13.2 components, verifies their
SHA-256 checksums, and installs them into `m4a-scribe/.runtime/toolkit`. It needs no
sudo and makes no changes to system packages, apt repositories, or shell profiles.
Run the dependency helper without `--cuda` separately as shown in step 2.

Then open the app, select a preset and **GPU**, and click **Set up GPU**:

```sh
./m4a2txt
```

For a complete High + GPU setup from the terminal instead:

```sh
sh m4a-scribe/scripts/build-engine.sh cuda
python3 m4a-scribe/scripts/install-model.py large-v3 --download
./m4a2txt --check
./m4a2txt
```

Select **High** and **GPU** in the window. For Mid, substitute
`large-v3-turbo-q5_0` in the model command and select **Mid**.

**The `cuda` argument matters.** Running `sh m4a-scribe/scripts/build-engine.sh`
without an argument builds the CPU engine, even after installing the toolkit.
`Built cpu engine at ...` means that CPU build succeeded; it is not a GPU build
failure. Run the command again with `cuda`, or use **Set up GPU**. A CPU build is
not required before a CUDA build, and the two engines can coexist.

The build automatically finds the project-local toolkit, including when started
from the GUI. Keep the toolkit alongside the engine after setup: its libraries
are needed during transcription too. A compatible NVIDIA driver is still required.

If you already maintain a compatible CUDA toolkit, you can skip the toolkit
download and select its compiler with `CUDACXX=/path/to/bin/nvcc` or
`CUDA_HOME=/path/to/toolkit`. Explicit overrides take precedence over the local
toolkit. See the [advanced CUDA setup notes](m4a-scribe/README.md#manual-or-offline-setup)
for host compiler and architecture overrides.

### Follow setup progress

**Set up CPU** and **Set up GPU** show progress for **Laptop**, **Mid**, and
**High**. The bar stays at the bottom of the window while setup runs:

- Engine compilation shows its reported build percentage, such as **Building
  CUDA engine: 76%**. CPU builds use the same display. A single compilation step
  can take a while, so the percentage can stay unchanged while work continues.
- Model downloads show bytes received and a percentage when the server provides
  the total size. If the size is unavailable, the app shows received bytes and an
  animated bar. This applies to all three preset models.
- Preparing, configuring, and verifying use an animated bar. An activity spinner
  and elapsed time stay visible throughout setup. Percentages describe the
  current stage, not time remaining or overall installation completion.

Click **See Details For Log**, or the **Details** button, to see the live setup
log. Compiler diagnostics appear there without replacing the progress percentage.
After a download reaches 100%, the model still needs checksum verification. An
existing model is verified without downloading it again; an installed engine is
reused. Wait for **Setup complete** before transcribing. **Cancel** stops setup;
failed or cancelled setup is not reported as complete.

The terminal build and model installer also print progress. The GUI tracks setup
started through its own setup button; it does not attach to an independently
started terminal build. After updating the application, let any current setup
finish, then close and reopen the app to load the new display. Whisper's existing
transcription progress display is unchanged.

## 4. Choose a model

| Desktop preset | Model installer argument | Approximate download |
| --- | --- | --- |
| Laptop | `small.en` | 466 MiB |
| Mid | `large-v3-turbo-q5_0` | 547 MiB |
| High | `large-v3` | 2.9 GiB |

Each preset works with either processor and shares the same model file between
CPU and GPU. Download sizes are not GPU memory requirements. If High runs out of
GPU memory, select Mid and set up its model, or explicitly select CPU. Switching
presets preserves your CPU/GPU choice; the app does not substitute a smaller model
automatically.

Manual engine builds do not install a model. The model installer verifies the
file against the pinned upstream SHA-1 digest and records a local SHA-256 checksum.
To import an already downloaded model instead:

```sh
python3 m4a-scribe/scripts/install-model.py small.en \
  --from-file "/path/to/ggml-small.en.bin"
```

This avoids a model download; native dependencies and the engine still need to be
installed. The engine build normally retrieves pinned whisper.cpp source from
GitHub during its first run.

## 5. Verify with a transcription

```sh
./m4a2txt --version
./m4a2txt --check
./m4a2txt
```

Choose the preset and processor you installed, add a short audio file, and click
**Transcribe**. The desktop starts with `~/Documents/Transcripts` as its output
folder unless you have saved another choice. Completed GPU jobs should report a
CUDA backend, for example **GPU (CUDA0)**. GPU mode stops on an error rather than
silently retrying on CPU.

For a CLI check after installing High + GPU:

```sh
mkdir -p "$HOME/Documents/Transcripts"
./m4a2txt --cli \
  --model m4a-scribe/models/ggml-large-v3.bin \
  --device gpu --threads 8 \
  --output-dir "$HOME/Documents/Transcripts" \
  "/path/to/episode.m4a"
```

Replace the audio path with your own regular local file. For the Laptop + CPU
setup, use `m4a-scribe/models/ggml-small.en.bin` and `--device cpu`. The CLI output
directory must already exist. CLI `--device auto` allows CPU fallback; choose
`--device gpu` when verifying GPU execution. The desktop transcribes English;
other supported language codes and `--language auto` are available through the CLI.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `Built cpu engine` after installing CUDA | Supply `cuda` to `build-engine.sh`, then install a model or use **Set up GPU**. The no-argument build defaults to CPU. |
| Missing GTK bindings or desktop unavailable | Run `./install-deps.sh`, then `./m4a2txt` from a graphical desktop session. The launcher uses Ubuntu's system Python. |
| `Unsupported gpu architecture 'compute_120a'` | The selected CUDA compiler is too old for this target. Install the project-local toolkit and rebuild with `cuda`. Check for an explicit `CUDACXX` or `CUDA_HOME` pointing to an older toolkit. |
| CUDA host compiler or header check fails | Use a toolkit compatible with your host compiler and headers. The project-local CUDA 13.2 path was validated with Ubuntu 26.04.1 and GCC 15.2.0; advanced overrides are documented in the app README. |
| `nvcc --version` still reports an old system version | Run `m4a-scribe/.runtime/toolkit/bin/nvcc --version` to inspect the local toolkit. No PATH change is needed; `./m4a2txt --check` reports the compiler the app selects. |
| `nvidia-smi` works but no CUDA compiler is found | Driver availability and compiler availability are separate. Install the toolkit; the CUDA version shown by `nvidia-smi` does not prove `nvcc` is installed. |
| Engine built, but setup still requests a model | Install the model for the selected preset. Building either engine does not download weights. |
| Toolkit download interrupted | Rerun `./install-deps.sh --cuda`. Normal interrupted installs do not activate a partial toolkit. If it reports an incomplete or different destination, move that directory aside before retrying. |
| Cannot save to a FAT/exFAT drive | Choose a local output directory on a filesystem with hard-link support, such as ext4, then copy the finished transcript to the external drive. |

Git's detached-HEAD notice is expected when the build checks out the pinned
whisper.cpp revision. A CMake deprecation warning or missing optional `ccache`
warning alone does not mean the build failed. Look for a successful exit and the
final `Built cpu engine` or `Built cuda engine` message.

For an existing checkout, close the app and use `git pull --ff-only` on your update
branch before repeating the relevant setup commands. This installs no toolkit or
model automatically. When the selected CUDA toolchain changes, a manual CUDA
rebuild preserves the old build under `m4a-scribe/.runtime/cuda-previous.*` and
configures a fresh one; CPU engines and models are kept separately.

See the [usage guide](m4a-scribe/README.md) for batch processing and data limits,
and the [validation record](m4a-scribe/VALIDATION.md) for executed checks.
