#!/bin/sh
# Explicit setup command, invoked manually or by the desktop's Set up button.
set -eu
mode=${1:-cpu}
[ "$#" -le 1 ] || { echo 'Usage: scripts/build-engine.sh cpu|cuda' >&2; exit 2; }
case "$mode" in cpu|cuda) ;; *) echo 'Usage: scripts/build-engine.sh cpu|cuda' >&2; exit 2 ;; esac
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
pin=d1be6fde11ac6e0407606b4e42fe72d34add8037
source_dir="$root/.runtime/source"
build_dir="$root/.runtime/$mode"
for tool in git cmake; do
    command -v "$tool" >/dev/null 2>&1 || { echo "Missing $tool; see README setup." >&2; exit 1; }
done
set --
if [ "$mode" = cuda ]; then
    # Explicit overrides win; otherwise prefer our verified toolkit over an old
    # /usr/bin/nvcc. Desktop launches need no PATH or shell-profile changes.
    nvcc=${CUDACXX:-}
    if [ -z "$nvcc" ] && [ -n "${CUDA_HOME:-}" ]; then nvcc="$CUDA_HOME/bin/nvcc"; fi
    if [ -z "$nvcc" ] && [ -x "$root/.runtime/toolkit/bin/nvcc" ]; then nvcc="$root/.runtime/toolkit/bin/nvcc"; fi
    if [ -z "$nvcc" ]; then nvcc=$(command -v nvcc || true); fi
    if [ -z "$nvcc" ] && [ -x /usr/local/cuda/bin/nvcc ]; then nvcc=/usr/local/cuda/bin/nvcc; fi
    nvcc=$(command -v "${nvcc:-nvcc}") || {
        echo 'CUDA compiler nvcc is missing. Run ./install-deps.sh --cuda from the package root.' >&2; exit 1;
    }
    version=$("$nvcc" --version)
    printf '%s\n%s\n' "CUDA compiler: $nvcc" "$version"
    architectures=${SCRIBE_CUDA_ARCHITECTURES:-}
    if [ -z "$architectures" ] || [ "$architectures" = native ]; then
        capabilities=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader) || {
            echo 'Cannot query the NVIDIA driver. Check nvidia-smi in your desktop session.' >&2; exit 1;
        }
        architectures=$(printf '%s\n' "$capabilities" | tr -d '. ' | sort -u | paste -sd ';' -)
    fi
    supported=$("$nvcc" --list-gpu-code)
    # Match the pinned upstream's conversion of 12x to 12xa targets.
    old_ifs=$IFS
    IFS=';'
    set -f
    for architecture in $architectures; do
        code=${architecture%-real}
        code=${code%-virtual}
        case "$code" in 12[0-9]) code="${code}a" ;; esac
        # nvcc lists base targets only, even when it accepts 120a/120f.
        base_code=${code%a}
        base_code=${base_code%f}
        if ! printf '%s\n' "$supported" | grep -Fx "sm_$base_code" >/dev/null; then
            echo "Selected nvcc cannot build GPU architecture $code. RTX 50-series needs CUDA 12.8 or newer." >&2
            echo 'Run ./install-deps.sh --cuda from the package root, then retry. CUDACXX overrides automatic selection.' >&2
            exit 1
        fi
    done
    set +f
    IFS=$old_ifs
    [ -n "$architectures" ] || { echo 'No CUDA GPU architecture detected.' >&2; exit 1; }
    # Catch incompatible host compiler/headers before the full engine build.
    probe=$(mktemp -d)
    trap 'rm -rf "$probe"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' HUP TERM
    printf '#include <cuda_runtime.h>\n__global__ void probe() {}\n' > "$probe/probe.cu"
    if [ -n "${CUDAHOSTCXX:-}" ]; then set -- "-ccbin=$CUDAHOSTCXX"; fi
    if ! "$nvcc" "$@" -arch="sm_$code" -c "$probe/probe.cu" -o "$probe/probe.o"; then
        echo 'CUDA compiler/host compiler check failed. Use a toolkit compatible with your GCC and system headers.' >&2
        echo 'On Ubuntu 26.04, ./install-deps.sh --cuda installs CUDA 13.2 with GCC 15 support.' >&2
        exit 1
    fi
    rm -rf "$probe"
    trap - EXIT HUP INT TERM
    # CMake caches compiler and library paths. Retain the previous build instead
    # of mixing its CUDA 12.4 objects/libraries into the replacement toolkit.
    signature=$(printf '%s\n' "$nvcc" "$version" "${CUDAHOSTCXX:-}" "${CC:-}" "${CXX:-}" "$architectures")
    if [ -d "$build_dir" ] && { [ ! -f "$build_dir/scribe-toolchain" ] || [ "$(cat "$build_dir/scribe-toolchain")" != "$signature" ]; }; then
        backup=$(mktemp -d "$root/.runtime/cuda-previous.XXXXXX")
        rmdir "$backup"
        mv "$build_dir" "$backup"
        printf 'Previous CUDA build preserved at %s\n' "$backup"
    fi
    mkdir -p "$build_dir"
    printf '%s\n' "$signature" > "$build_dir/scribe-toolchain"
    set -- "-DCMAKE_CUDA_COMPILER=$nvcc" "-DCMAKE_CUDA_ARCHITECTURES=$architectures"
    if [ -n "${CUDAHOSTCXX:-}" ]; then set -- "$@" "-DCMAKE_CUDA_HOST_COMPILER=$CUDAHOSTCXX"; fi
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
# Architecture overrides remain one quoted CMake list, including in compile-only CI.
cmake -S "$source_dir" -B "$build_dir" \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    -DWHISPER_BUILD_IS_DEV=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF \
    -DWHISPER_CURL=OFF -DGGML_RPC=OFF -DGGML_BACKEND_DL=OFF \
    -DGGML_NATIVE=ON -DGGML_CUDA="$cuda" "$@"
cmake --build "$build_dir" --config Release --parallel "${SCRIBE_BUILD_JOBS:-4}" --target whisper-cli
# Compile-only CI has the toolkit's link stubs but no installed NVIDIA driver.
# Normal desktop setup still executes the engine to verify runtime linkage.
if [ "${SCRIBE_BUILD_ONLY:-0}" != 1 ]; then
    "$build_dir/bin/whisper-cli" --version
fi
printf '\nBuilt %s engine at %s/bin/whisper-cli\n' "$mode" "$build_dir"
