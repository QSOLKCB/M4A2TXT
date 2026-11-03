# M4A2TXT

Local M4A-to-text conversion using your own CPU or GPU. **M4A Scribe 0.3.0-preview** provides a GTK 4 / libadwaita desktop with **Laptop / Mid / High** model presets, an independent **CPU / GPU** toggle, and a batch CLI backed by Whisper.

The source lives in [`m4a-scribe/`](m4a-scribe/). Start with its [setup and usage guide](m4a-scribe/README.md).

![Native GTK desktop with Laptop, Mid, and High presets](docs/gtk-preview.png)

Earlier 0.2.0 GTK window from the [automated UI check](https://github.com/QSOLKCB/M4A2TXT/actions/runs/41537925273), with example audio. The current version adds a CPU/GPU toggle beneath the presets. This screenshot is not a GPU performance result.

## Get started

Use this source checkout, or download the `m4a2txt-linux` artifact from a successful [Local app checks run](https://github.com/QSOLKCB/M4A2TXT/actions/workflows/tests.yml) for the desired commit and extract it. The [earlier 0.2.0 package](packages/README.md) is preserved but does not include the CPU/GPU toggle.

From the repository root, or the top of an extracted [Linux package](PACKAGING.md):

```sh
./m4a2txt
```

Select **Laptop**, **Mid**, or **High**, then choose **CPU** or **GPU**. Use the clearly labelled one-time setup button if needed, and drop audio files onto the window. **Mid + GPU** uses quantized Whisper turbo on CUDA; **High + GPU** uses the full large-v3 model on CUDA. CPU uses the same selected model with GPU execution disabled. The processor choice is remembered and does not change when switching presets.

GPU mode requires a compatible NVIDIA driver and CUDA toolkit for setup. It stops on a GPU error instead of silently retrying on CPU. Successful jobs show the reported CUDA backend. See the [CUDA workflow and hardware check](m4a-scribe/README.md#cuda-validation-workflow).

On Ubuntu 24.04+, run `./install-deps.sh` once if the native dependencies are missing. `./m4a2txt --check` checks your local setup without downloading anything. See [package instructions](PACKAGING.md) for extraction, verification, and rebuilding the deterministic archive. The package uses your operating system's Python, GTK and FFmpeg; it installs the selected model and builds its engine during explicit first-time setup.

After setup, transcription runs locally without a cloud service, chat interface, or HTTP server. Model installation is a separate, explicit operation. The application exports plain UTF-8 `.txt` files without adding summaries or rewriting the recognizer's text.

## Source and evidence

| Location | Contents |
| --- | --- |
| [`m4a-scribe/`](m4a-scribe/) | Extracted app, setup scripts, tests, and documentation |
| [`m4a-scribe/DESIGN.md`](m4a-scribe/DESIGN.md) | Architecture and implementation stages |
| [`m4a-scribe/VALIDATION.md`](m4a-scribe/VALIDATION.md) | Executed checks and remaining validation |
| [`docs/OPT-ADAPTATION.md`](docs/OPT-ADAPTATION.md) | OPT patterns, measured fixture reuse, and verified compiler-cache workflow |
| [`archive/`](archive/) | Original uploaded bundle and its checksum |

This remains a source preview. The test suite covers the local pipeline, desktop queue, cancellation, setup choices, and real GTK widget flows. See the validation record and GitHub Actions for executed results. GPU operation and full-length Audio Overview accuracy still require validation on the target machine.

## Verify the extraction

```sh
(cd archive && sha256sum -c SHA256SUMS)
(cd m4a-scribe && sha256sum -c SHA256SUMS)
```

The original compressed bundle is preserved byte-for-byte. The application now develops in `m4a-scribe/`; its current checksums are separate from the retained preview baseline in `validation/preview-0.1.0-SHA256SUMS`.

## Licences

The repository's existing [Apache 2.0 licence](LICENSE) is retained. The imported M4A Scribe package keeps its original [MIT licence](m4a-scribe/LICENSE). Upstream Whisper, whisper.cpp, and the installed FFmpeg build retain their respective notices; their weights and binaries are not included in this repository.
