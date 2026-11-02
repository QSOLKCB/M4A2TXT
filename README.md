# M4A2TXT

Local M4A-to-text conversion using your own CPU or GPU. The extracted **M4A Scribe 0.2.0-preview** provides a GTK 4 / libadwaita desktop with **Laptop / Mid / High** presets and a batch CLI backed by Whisper.

The source lives in [`m4a-scribe/`](m4a-scribe/). Start with its [setup and usage guide](m4a-scribe/README.md).

## Get started

From the repository root:

```sh
cd m4a-scribe
```

Follow the [Ubuntu setup instructions](m4a-scribe/README.md#ubuntu-setup) to install the GTK system packages once. Then launch:

```sh
sh run-scribe.sh
```

Select **Laptop**, **Mid**, or **High**, use the clearly labelled one-time setup button if needed, and drop audio files onto the window.

After setup, transcription runs locally without a cloud service, chat interface, or HTTP server. Model installation is a separate, explicit operation. The application exports plain UTF-8 `.txt` files without adding summaries or rewriting the recognizer's text.

## Source and evidence

| Location | Contents |
| --- | --- |
| [`m4a-scribe/`](m4a-scribe/) | Extracted app, setup scripts, tests, and documentation |
| [`m4a-scribe/DESIGN.md`](m4a-scribe/DESIGN.md) | Architecture and implementation stages |
| [`m4a-scribe/VALIDATION.md`](m4a-scribe/VALIDATION.md) | Executed checks and remaining validation |
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
