#!/bin/sh
# Explicit setup command, invoked manually or by the desktop's Set up button.
set -eu
mode=${1:-cpu}
case "$mode" in cpu|cuda) ;; *) echo 'Usage: scripts/build-engine.sh cpu|cuda' >&2; exit 2 ;; esac
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
pin=d1be6fde11ac6e0407606b4e42fe72d34add8037
source_dir="$root/.runtime/source"
build_dir="$root/.runtime/$mode"
for tool in git cmake; do
    command -v "$tool" >/dev/null 2>&1 || { echo "Missing $tool; see README setup." >&2; exit 1; }
done
if [ "$mode" = cuda ]; then
    command -v nvcc >/dev/null 2>&1 || { echo 'CUDA compiler nvcc is missing. Keep CPU mode, or install a compatible CUDA toolkit.' >&2; exit 1; }
fi
mkdir -p "$root/.runtime"
if [ ! -d "$source_dir/.git" ]; then
    git clone --branch v1.9.5 --depth 1 https://github.com/ggml-org/whisper.cpp.git "$source_dir"
fi
if [ -n "$(git -C "$source_dir" status --porcelain)" ]; then
    echo 'Engine source has local changes; refusing to overwrite them.' >&2
    exit 1
fi
if ! git -C "$source_dir" cat-file -e "$pin^{commit}" 2>/dev/null; then
    git -C "$source_dir" fetch origin "$pin"
fi
git -C "$source_dir" checkout --detach "$pin"
test "$(git -C "$source_dir" rev-parse HEAD)" = "$pin"
cuda=OFF
if [ "$mode" = cuda ]; then cuda=ON; fi
cmake -S "$source_dir" -B "$build_dir" \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    -DWHISPER_BUILD_IS_DEV=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF \
    -DWHISPER_CURL=OFF -DGGML_RPC=OFF -DGGML_BACKEND_DL=OFF \
    -DGGML_NATIVE=ON -DGGML_CUDA="$cuda"
cmake --build "$build_dir" --config Release --parallel "${SCRIBE_BUILD_JOBS:-4}" --target whisper-cli
"$build_dir/bin/whisper-cli" --version
printf '\nBuilt %s engine at %s/bin/whisper-cli\n' "$mode" "$build_dir"
