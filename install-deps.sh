#!/bin/sh
# Explicit system setup, never invoked by the application itself.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -eq 1 ] && [ "$1" = --cuda ]; then
    # Optional, user-owned toolkit. No sudo, repositories, or driver changes.
    exec python3 "$root/m4a-scribe/scripts/install-cuda.py" --download
fi
if [ "$#" -ne 0 ]; then
    echo 'Usage: ./install-deps.sh [--cuda] (Ubuntu 24.04 or newer)' >&2
    echo 'No options: native desktop dependencies. --cuda: project-local CUDA toolkit only.' >&2
    exit 2
fi
command -v apt-get >/dev/null 2>&1 || {
    echo 'This helper needs Ubuntu apt-get. See m4a-scribe/README.md for dependencies.' >&2
    exit 2
}
if [ "$(id -u)" -eq 0 ]; then
    apt-get update
    apt-get install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 ffmpeg git cmake build-essential
else
    command -v sudo >/dev/null 2>&1 || { echo 'sudo is required to install system packages.' >&2; exit 2; }
    sudo apt-get update
    sudo apt-get install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 ffmpeg git cmake build-essential
fi
printf '\nDependencies installed. Start the desktop with ./m4a2txt\n'
printf 'For an RTX 50-series GPU, also run ./install-deps.sh --cuda, then set up GPU in the app.\n'
