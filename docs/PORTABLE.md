# Windows and macOS portable editions

The native-package workflow builds Windows x64, macOS Apple Silicon and macOS
Intel editions on their respective operating systems. These are self-contained
application folders: Python, Tk, whisper.cpp and a minimal FFmpeg audio decoder
are included. Keep the complete extracted folder together. Model weights are
separate so you can choose their size, download them explicitly, or select a
local `.bin` file. Normal transcription and translation need no network.

On Windows, open `M4A2TXT/M4A2TXT.exe`. The same executable accepts CLI arguments;
a console window accompanies the desktop in this preview. On macOS, open
`M4A2TXT.app`; its CLI is `M4A2TXT.app/Contents/MacOS/M4A2TXT`. Packages are not
Developer ID notarized or Windows Authenticode signed. macOS builds target macOS
15 or newer; x64 packages require AVX2-capable CPUs. These editions use the CPU;
Linux retains its existing explicit NVIDIA/CUDA option. Metal and native Windows
CUDA are future work, not capabilities of these downloads.

1. Choose a model preset and task. Translation is **speech into English**.
2. Use **Download model** for explicit first-time setup, or **Choose model file**
   to use an installed GGML model. No audio is uploaded.
3. Add local audio, choose TXT, SRT or VTT, and choose the output folder.
4. Start. Cancel stops the current job and keeps completed outputs. Existing
   outputs are never overwritten; another run gets a numbered filename.

The Laptop preset uses `small.en` for English transcription and multilingual
`small` for other languages or translation. Mid uses quantized Turbo for
transcription and multilingual `small` for translation. High uses `large-v3`.
Turbo and `.en` models cannot be selected for English translation. Source
language `auto` requests recognition-time language detection. Subtitle timing
comes directly from Whisper. Translation filenames contain `.en` so they are
identifiable beside source-language transcripts. Models can make mistakes;
review important passages and subtitle timings against the audio.

Use Tab to reach controls, Ctrl+O (Command+O on macOS) to add files,
Ctrl+Enter/Command+Enter to start, Escape to cancel, and Ctrl+Q/Command+Q to
close. Select a completed row and press Enter to read or copy its output.
**Larger transcript text** increases preview text. Linux GTK includes accessible
labels, selectable transcript text, Escape to cancel and Ctrl+E to open output.
Assistive-technology behavior still needs testing with actual screen readers,
especially the Tk edition; no screen-reader certification is claimed.

Models and settings live in `%LOCALAPPDATA%/m4a2txt` on Windows and
`~/Library/Application Support/m4a2txt` on macOS. `SCRIBE_DATA_HOME` overrides
model storage. User audio, models and transcripts are never included in a build.
Save outputs to a local filesystem with hard-link support (NTFS/APFS), not FAT
or exFAT. Atomic no-overwrite publication deliberately fails on unsupported
filesystems instead of risking existing files.

## Homebrew (macOS)

After this change is merged:

```sh
brew tap qsolkcb/m4a2txt https://github.com/QSOLKCB/M4A2TXT
brew install --HEAD qsolkcb/m4a2txt/m4a2txt
m4a2txt
```

The development formula builds pinned whisper.cpp locally and uses Homebrew's
Python/Tk and FFmpeg. It does not install model weights automatically. This is
an explicit custom tap, not a Homebrew/core formula or a published bottle.
`brew upgrade --fetch-HEAD m4a2txt` follows subsequent main-branch changes.

## Build and validation

`Native portable packages` produces checksummed archives as Actions artifacts
on pull requests, main updates, tags and manual runs. It does not publish a
release automatically. Native builds avoid treating PyInstaller as a cross
compiler. Dependencies used only for packaging are pinned with hashes in
`scripts/packaging-requirements.txt`. Build on each target OS with Python 3.12,
CMake and a native C/C++ compiler (MSYS2/MinGW plus make for FFmpeg on Windows):

```sh
python -m pip install --require-hashes -r scripts/packaging-requirements.txt
sh scripts/build-portable-ffmpeg.sh
python scripts/build-portable.py --ffmpeg .portable-build/ffmpeg/bin/ffmpeg
# Windows: use ffmpeg.exe in the last command.
python scripts/test-portable.py
```

FFmpeg is built from exact commit
`1041abdc962f4cc4f394aa8de9dc5236c0c3b9e7` (n8.1.3), with only local audio
protocols, selected audio codecs and PCM WAV output. Its corresponding source,
license, build recipe and configuration travel beside the application. It has
no network protocols or external codec libraries. Whisper is pinned to
`d1be6fde11ac6e0407606b4e42fe72d34add8037` (v1.9.5), with HTTP and RPC disabled.
Each package includes an application commit and per-file SHA-256 receipt.
Native binaries are not claimed to be byte-reproducible across different SDKs.

CI extracts each archive into a path containing spaces, verifies its manifest,
runs the bundled tools without host FFmpeg on PATH, and transcribes the public
upstream JFK sample with a verified tiny model. It exercises TXT/SRT/VTT and
an M4A decoder fixture. The GUI smoke test uses controlled jobs; it does not
measure human accessibility or speech accuracy.
