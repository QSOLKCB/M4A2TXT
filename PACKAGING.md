# M4A2TXT — Linux desktop package

## Start

Extract the archive, open a terminal in its folder, and run:

```sh
./m4a2txt
```

Supported desktop: Ubuntu 24.04 or newer, including Ubuntu 26.04. The launcher uses `/usr/bin/python3`, so an activated Python environment does not hide the operating system's GTK bindings. Keep the extracted folder together; the launcher can be called from another directory and accepts audio paths relative to that directory.

If dependencies are missing, run this once, then launch again:

```sh
./install-deps.sh
./m4a2txt
```

This explicit helper uses `sudo apt-get` to install Python, GTK, FFmpeg, and build tools. The app never runs it automatically. It does not install or change NVIDIA drivers. You can inspect it before running it.

Choose **Laptop**, **Mid**, or **High**. Click the clearly labelled **Set up** button the first time you use a preset; this downloads its model and builds the local engine. Then drop your `.m4a` files, click **Transcribe**, and open the resulting `.txt` files. After setup, transcription works offline. Mid and High use CUDA when available and visibly fall back to CPU otherwise. NVIDIA acceleration needs a compatible driver and CUDA toolkit already installed.

The bundle contains the application source and executable launcher. It uses the host's native GTK and FFmpeg; it does not bundle Python, system libraries, model weights, or a machine-specific engine binary. Engine builds happen on your machine so they target your CPU. This is a portable application folder, not an AppImage or a fully self-contained binary.

## Check and verify

```sh
./m4a2txt --version
./m4a2txt --check
sha256sum -c SHA256SUMS
```

`--check` is read-only and does not download models or require an active graphical display. Missing models are normal before first-time setup. The package includes its source commit in `SOURCE_COMMIT.txt` and checksums for every shipped file. Verify the archive's separate `.sha256` file before extracting if supplied.

Batch CLI use remains available:

```sh
./m4a2txt --cli --help
```

See [m4a-scribe/README.md](m4a-scribe/README.md) for detailed usage, the three preset models, offline setup, CUDA setup, and transcription limitations. See [m4a-scribe/VALIDATION.md](m4a-scribe/VALIDATION.md) for test evidence. GPU inference and full-episode accuracy still need validation on the target machine.

## Rebuild from the Git repository

From a checkout, package the files at a specific committed revision:

```sh
python3 scripts/package.py --ref HEAD --output-dir dist
```

Only explicitly selected application files from that Git commit are shipped. Working-tree edits, recordings, transcripts, settings, models, build directories, and old archives are excluded. The archive has stable ordering, ownership, permissions, and timestamps; rebuilding the same commit produces the same bytes.

The repository's root [Apache 2.0 licence](LICENSE) and the app's [MIT licence](m4a-scribe/LICENSE) are both included. This package does not redistribute Whisper weights, whisper.cpp binaries, or FFmpeg.
