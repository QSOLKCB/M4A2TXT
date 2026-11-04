#!/bin/sh
# Minimal LGPL audio decoder, built on the target OS. No external codec libraries.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
pin=1041abdc962f4cc4f394aa8de9dc5236c0c3b9e7 # FFmpeg n8.1.3
source_dir="$root/.portable-build/ffmpeg-source"
build_dir="$root/.portable-build/ffmpeg-build"
prefix="$root/.portable-build/ffmpeg"
mkdir -p "$root/.portable-build" "$build_dir" "$prefix"
if [ ! -d "$source_dir/.git" ]; then
    git clone --depth 1 --branch n8.1.3 https://github.com/FFmpeg/FFmpeg.git "$source_dir"
fi
test "$(git -C "$source_dir" rev-parse HEAD)" = "$pin"
test -z "$(git -C "$source_dir" status --porcelain)"
cd "$build_dir"
set --
case "$(uname -s)" in MINGW*|MSYS*) set -- --target-os=mingw32 --extra-ldflags=-static ;; esac
"$source_dir/configure" --prefix="$prefix" \
    --disable-autodetect --disable-network --disable-doc --disable-debug \
    --disable-shared --enable-static --disable-x86asm --disable-everything \
    --disable-programs --enable-ffmpeg --enable-swresample \
    --enable-protocol=file,pipe --enable-demuxer=mov,mp3,wav,flac,aac,ogg \
    --enable-decoder=aac,aac_fixed,alac,mp3,mp3float,flac,opus,vorbis,pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_s32be,pcm_f32le,pcm_f32be,pcm_f64le,pcm_f64be,pcm_u8,pcm_alaw,pcm_mulaw \
    --enable-parser=aac,mpegaudio,flac,opus,vorbis \
    --enable-filter=aresample,aformat,anull --enable-encoder=pcm_s16le --enable-muxer=wav "$@"
make -j "${SCRIBE_BUILD_JOBS:-4}"
make install
# Ship corresponding source and the exact build recipe beside the executable.
git -C "$source_dir" archive --format=tar --prefix=ffmpeg/ "$pin" | gzip -n > "$prefix/ffmpeg-source.tar.gz"
cp "$source_dir/COPYING.LGPLv2.1" "$prefix/FFMPEG-LICENSE.txt"
cp "$0" "$prefix/build-portable-ffmpeg.sh" 2>/dev/null || cp "$root/scripts/build-portable-ffmpeg.sh" "$prefix/build-portable-ffmpeg.sh"
cp config.h "$prefix/config.h"
cp ffbuild/config.log "$prefix/config.log"
