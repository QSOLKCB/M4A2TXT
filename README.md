# M4A2TXT

Local M4A-to-text conversion using your own CPU or GPU. The extracted **M4A Scribe 0.1.0-preview** provides a native desktop window and batch CLI backed by Whisper.

The source lives in [`m4a-scribe/`](m4a-scribe/). Start with its [setup and usage guide](m4a-scribe/README.md).

## Get started

From the repository root:

```sh
cd m4a-scribe
```

Follow the [Ubuntu setup instructions](m4a-scribe/README.md#ubuntu-setup) to install system dependencies, build the local engine, and install a model. Then launch:

```sh
sh run-scribe.sh
```

After setup, transcription runs locally without a cloud service, chat interface, or HTTP server. Model installation is a separate, explicit operation. The application exports plain UTF-8 `.txt` files without adding summaries or rewriting the recognizer's text.

## Source and evidence

| Location | Contents |
| --- | --- |
| [`m4a-scribe/`](m4a-scribe/) | Extracted app, setup scripts, tests, and documentation |
| [`m4a-scribe/DESIGN.md`](m4a-scribe/DESIGN.md) | Architecture and implementation stages |
| [`m4a-scribe/VALIDATION.md`](m4a-scribe/VALIDATION.md) | Executed checks and remaining validation |
| [`archive/`](archive/) | Original uploaded bundle and its checksum |

This remains a source preview. The retained validation covers the CPU transcription path and 19 pipeline regression tests; GPU operation, the desktop's visual layout, and full-length Audio Overview accuracy still require validation on the target machine.

## Verify the extraction

```sh
(cd archive && sha256sum -c SHA256SUMS)
(cd m4a-scribe && sha256sum -c SHA256SUMS)
```

The extracted files and original compressed bundle are preserved byte-for-byte. The package directory retains the original name so its scripts, documentation, and checksums remain consistent.

## Licences

The repository's existing [Apache 2.0 licence](LICENSE) is retained. The imported M4A Scribe package keeps its original [MIT licence](m4a-scribe/LICENSE). Upstream Whisper, whisper.cpp, and the installed FFmpeg build retain their respective notices; their weights and binaries are not included in this repository.
