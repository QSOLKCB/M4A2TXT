#!/bin/sh
# Explicit system setup, never invoked by the application itself.
set -eu
if [ "$#" -ne 0 ]; then
    echo 'Usage: ./install-deps.sh (Ubuntu 24.04 or newer)' >&2
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
