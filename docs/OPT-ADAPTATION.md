# OPT adaptation: build and test reuse

Source: [QSOLKCB/OPT at 7556dd36](https://github.com/QSOLKCB/OPT/tree/7556dd36acd53ed3ed538fd03b1db44e5c1ec869), including its AI usage guide, optimization problem contract, catalog, OPT-INV-001, OPT-PY-001, OPT-INC-001 and the Wonderbuild source note. These are adapted patterns; no Wonderbuild implementation or donor performance numbers are copied. No OPT theorem is claimed to prove this application.

## Contract declared before measurement

| Field | Target contract |
| --- | --- |
| X | Fresh/reused immutable test fixture; empty/restored compiler cache; forced clean rebuilds |
| F | Same tests and assertions, same compiler/toolkit/source/architecture inputs, bounded cache, explicit fresh path |
| f, d | Minimize repeated test/build wall time, accounting for fixture creation and compiler-cache lookup within the measured stages |
| C | Identical fixture bytes, isolated per-test input files, exact cached/fresh canary object bytes and rebuilt engine digest, unchanged transcript behavior and CUDA checks; failures must not become successful cache entries |
| B | Five paired fresh/reused test-suite runs; one first CUDA build and two forced-clean warm builds; small C++/CUDA cache invalidation/corruption canaries; 90-minute CUDA job and 2 GiB cache cap |
| S | Reject on parity or isolation failure. Stop after the budget. Report measured distributions; retain performance claims only when the measured median improves by at least 10%. No timing threshold weakens correctness checks. |
| Classification | Categorical variables; local scope; noisy timing/deterministic parity; derivative-free; moderate/expensive evaluation; semantic/integrity/resource constraints; bounded build parallelism; exact reuse, no new approximation |

## Test fixture reuse — OPT-INV-001 / OPT-PY-001

Named invariant: `FIXED_M4A_FIXTURE`. Every pipeline test starts with the same FFmpeg-generated quarter-second sine encoded as AAC/M4A. Generate its immutable bytes once per test process and write a separate copy into each test's private directory. Tests that corrupt, empty or replace their file cannot mutate the retained bytes or another test's file. Real FFmpeg decoding still runs for every applicable case. Existing edge cases and assertions stay intact.

`SCRIBE_TEST_FRESH_FIXTURES=1` retains the per-test encoding reference. Compare fresh and reused bytes directly and compare the same complete suite under both modes. Benchmark timings include test setup/teardown. The fixture is process-local, bounded, and never reused across FFmpeg/toolchain changes or application runs.

## Routine CI and full parity mode

The original three-build experiment below remains available through manual
`full_parity: true`. Routine CUDA jobs now verify and restore a linked engine
for an exact toolchain/configuration identity, or build once with compiler reuse
on a miss. A separate receipt binds the executable and CMake configuration bytes
to that identity. Missing, modified, mismatched or symlinked cache entries are
rejected. The normal CUDA ELF, architecture and symbol checks still execute on
restored engines. No application or GPU test result is cached.

`force_cold: true` skips both external caches; combine it with `full_parity` for
the original complete experiment. Application/UI-only edits run the application
and packaging tests without rebuilding an unchanged CUDA engine. This changes
workflow cost, not inference settings. No new timing speedup is claimed until
actual cache-hit/miss runs are compared. Caches remain bounded by GitHub's cache
policy, and the compiler cache retains its explicit 2 GiB cap.

The records below describe the original full-parity experiment. Its configure,
link and three-build statements apply to full parity mode; exact engine-cache
hits intentionally skip those compilation stages and say so in their receipt.

## Compiler reuse — OPT-INC-001 adaptation

Use ccache's preprocessor mode for C/C++/CUDA translation units, with compiler-content checks, no sloppiness or hard-linked outputs, and a 2 GiB bound. Source, preprocessed headers and compilation options remain part of ccache's lookup. An additional immutable CI toolchain manifest binds the runner image, installed packages, compiler versions/content, CPU features used by native compilation, architecture list, build configuration and cache-check implementation. The external cache key has no broad restore prefix.

This is compiler object reuse in an isolated CI checkout, not a cache of test results, models, transcripts, or authoritative application generations. CMake configuration, linking, binary-format/CUDA-symbol checks and application tests still execute. The compile-only hosted job sets `SCRIBE_BUILD_ONLY=1` because it has toolkit link stubs but no actual NVIDIA driver supplying `libcuda.so.1`. Normal desktop setup and the manual hardware job still execute the built engine's version check. The cache is saved only after the build and parity checks succeed. A manual cold option skips external restoration. A cache hit is never labelled a cold reconstruction.

Trust/snapshot boundary: the CI checkout and installed toolchain are fixed during each build; no concurrent source/toolchain/cache writers are permitted in that job. GitHub cache access is scoped by ref and exact key; restored data is processed by ccache's integrity checks. This adaptation does not claim protection against a malicious compiler/cache service, privileged concurrent filesystem mutation, or general live-input A→B→A races. Do not transplant it into mutable application-result caching without the additional generation/handle/linearization requirements in OPT-INC-001.

CUDA canaries compare cached outputs against a fresh compiler invocation, including unchanged input, changed header/flags, restored input, missing outputs, compiler failure and corrupted cache contents. Forced-clean warm engine rebuilds must produce the same executable digest and report cache hits. Record actual ccache statistics and stage timings; requested worker counts are not measured concurrency.

CI sets NVCC's documented [`--objdir-as-tempdir`](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-compiler-driver-nvcc/index.html#objdir-as-tempdir-objtemp) option for stable intermediate filenames. The initial CUDA 12.8 canary correctly rejected unequal fresh/cached object bytes: their only differences were the process-dependent `tmpxft` filename bytes in the ELF symbol table. Object-directory temporaries fix that source of nondeterminism without weakening the comparison. Each translation unit has its own CMake output path; the three build phases execute sequentially, so variants of the same source never compile concurrently into one directory. This option affects CI temporary placement and build metadata, not Whisper's recognition settings.

## Evidence and limits

The [test-stage record](evidence/opt-tests.json) contains all ten raw runs, environment details, test identities and tested-file hashes. Five alternating pairs executed the same 39 cases without skips. On that host, fresh median was **4.925 s**, reused median **3.670 s**: **25.5% less test wall time (1.34×)**. This is a local test-stage measurement, not an inference benchmark or a claim about every machine.

Compiler-cache measurements are pending the CUDA workflow. Each run uploads its toolchain manifest, fresh/cached canary results, three build logs, exact engine digests, per-phase cache statistics and elapsed times as `cuda-build-evidence`. The manual `force_cold` input skips restoration. A restored-first run is reported separately from an empty-first run; cache transport and toolkit installation are excluded from the build-stage timer. The 90-minute ceiling accommodates the observed long first compilation plus two required warm rebuilds; parallelism stays bounded at two workers.

CI runs once per pull-request update and on main pushes, and cancels superseded checks on the same ref. Every regression case still executes, including the complete fresh-fixture suite and the packaged reused-fixture suite.

The target is repeated CI compilation and deterministic test setup. This does not reduce the first model download, eliminate the first CUDA compilation, or establish faster GPU inference. CUDA decoding kernels, Whisper model choices and recognition settings are unchanged. Hardware inference and VRAM measurements remain separate acceptance work.

Rollback: set `SCRIBE_TEST_FRESH_FIXTURES=1`, bypass ccache with `CCACHE_DISABLE=1`, or remove the optional compiler-cache CI steps if parity fails or measured overhead exceeds avoided work. Preserve the cold and reference checks when changing cache policy.
