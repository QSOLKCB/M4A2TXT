# M4A Scribe design

Design baseline: 3 November 2026. Target: a local Ubuntu desktop utility that turns Audio Overview `.m4a` exports into plain UTF-8 text. The AI is a speech recognition component, with no conversational interface or external inference service.

## User experience

The normal task is: choose one or more audio files, choose the output folder, click Transcribe, and open the resulting text. The application remembers the installed model and processor preference. A batch runs one file at a time to keep memory use predictable.

The interface has one native window: file queue; local model and destination selectors; Auto, GPU preferred, or CPU mode; language; Transcribe and Cancel; transcript preview; playback; and an optional Details tab. Setup and diagnostics are separate from the transcript itself.

The initial toolkit is Python's standard Tk/ttk binding. It needs the operating system's `python3-tk` package, but no pip environment. If a more integrated GNOME appearance becomes a priority, the same core can be called from GTK later; a second UI is not necessary for the initial tool.

## Components

| Component | Responsibility | Boundary |
| --- | --- | --- |
| Tk desktop / CLI | User choices, queue, presentation, cancellation | No model downloads or HTTP server |
| Python core | Validate local input, supervise children, publish complete text | Calls executables with argument arrays, not a shell |
| FFmpeg | Decode local media to canonical audio | File/pipe protocols only; explicit demuxer; no network inputs |
| whisper.cpp CPU executable | Run Whisper with GPU disabled | Independent CPU build |
| whisper.cpp CUDA executable | Request NVIDIA acceleration | Optional build; same model and transcript interface |
| Setup scripts | Build pinned engine and install chosen model | Network use is explicit and confined to setup |

No transport API is required. UI-to-core calls are ordinary Python calls and an in-process event queue; core-to-engine communication uses process arguments, temporary files, and logs. No port is bound, including localhost. The OS desktop and audio stack can use their normal local IPC.

## Job state and publication

```mermaid
stateDiagram-v2
    [*] --> Queued
    Queued --> Decoding
    Decoding --> Recognising
    Recognising --> CPU_retry: Auto and CUDA failure
    CPU_retry --> Publishing: Complete transcript
    Recognising --> Publishing: Complete transcript
    Publishing --> Saved: Atomic no-overwrite link
    Decoding --> Failed: Invalid or excessive input
    Recognising --> Failed: Engine failure
    CPU_retry --> Failed: Retry failure
    Decoding --> Cancelled: Cancel
    Recognising --> Cancelled: Cancel
    CPU_retry --> Cancelled: Cancel
    Publishing --> Cancelled: Cancel before commit
    Saved --> [*]
    Failed --> [*]
    Cancelled --> [*]
```

The file publication operation is the completion boundary. Cancellation before it publishes nothing for that job. Cancellation after it cannot retract a completed transcript. A cancelled batch preserves earlier completed files. The GUI can finish reporting a completed job even if a cancellation arrives just after publication.

Atomic hard-link publication avoids the race in “check whether a name exists, then overwrite it.” A collision selects a new name. Publication is currently restricted to filesystems that support this operation. Input filenames remain data, including spaces, quotes, Unicode, and shell metacharacters.

## Recognition policy

The initial defaults are English transcription, temperature zero, temperature fallback disabled, no initial prompt, no grammar constraints, no VAD, and no translation. Do not introduce cleanup by a second language model. These choices make the app's transformations inspectable; they are not a promise of exact recognition or bit-identical results across CPU and GPU.

The text returned by whisper.cpp is the exported text, including its punctuation and line breaks. The app must not repair a speaker's factual mistakes or calculations. Whisper may itself normalize speech, omit hesitations, or hallucinate; exact experimental quotations still need audio review.

Start with unquantized `large-v3-turbo` for clean overview audio. Compare full `large-v3` against the same reference clips before changing the preferred model. `small.en` offers a smaller CPU option selected explicitly by the user. Quantized models are a future selectable memory/performance trade-off, not an automatic downgrade.

Do not infer speaker identity from alternating sentences or stereo channel layout. The two hosts may be mixed into both channels. Reliable speaker turns require a separately evaluated local diarization system; host names require explicit user assignment. Plain text is useful without this additional model.

## Local operation

The runtime has no download code or cloud fallback. Network-capable setup lives in a separate script that is never imported or invoked by the app. The shipped build configuration disables whisper.cpp's CURL and server support and ggml's RPC backend. Custom executable paths are a user-controlled trust boundary; arbitrary replacement executables are not guaranteed to be offline.

The app preserves the original audio and decodes a private copy. Temporary decoded audio can be larger than the compressed source: 16,000 samples/second × 2 bytes gives about 115 MB per hour before the recognizer's in-memory representation and model buffers. Whole-file decoding has a four-hour preview cap. OS crashes may leave temporary material; no secure-erasure claim is made.

The batch queue is in memory. Settings store paths and options only. No transcript database, telemetry, remote analytics, or cloud account is part of the design. Setup can be completed elsewhere and transferred, subject to compatible binaries and normal dependency installation.

## GPU and CPU behaviour

Auto selects the installed CUDA executable first and retries the entire file once on the independent CPU executable if the first attempt fails. It reuses the decoded PCM and the same model; no partial transcript from the first attempt is combined with the retry. The reason for fallback is visible in Details.

GPU preferred uses the CUDA executable without that wrapper-level retry. Because whisper.cpp can choose its own backend internally, this preview does not advertise that selecting this mode proves GPU offload. A later small native worker around the C API can provide machine-readable actual backend information and progress/abort callbacks without parsing diagnostic output.

For the user's NVIDIA desktop, CUDA is the intended accelerated path. On machines without a working proprietary driver/toolkit combination, CPU remains usable. Available VRAM and driver compatibility must be measured on the real machine; neither the GPU model name nor an installed `nvcc` alone establishes a successful inference path.

## Release stages

| Stage | Deliverable | Exit condition |
| --- | --- | --- |
| Starter, included here | Local batch CLI, native window, FFmpeg decode, Whisper adapter, cancellation, safe output, setup scripts | Local wrapper tests and documented engine smoke results |
| Hardware validation | RTX GPU run and Ryzen CPU run using representative episodes | Capture actual backend, wall time, peak RAM/VRAM, and reviewed transcript differences |
| Transcript review | Segment timestamps and seek-to-audio; manual edits saved separately | Raw machine output retained; timestamps map to original audio |
| Evidence exports | Optional JSON receipt with source/model/engine/output hashes and settings | Metadata stays out of `.txt`; failed runs cannot claim complete evidence |
| Desktop release | Versioned package, launcher, installed-runtime paths | Clean Ubuntu install and offline launch tested; dependencies/licences accounted for |

The starter does not implement diarization, timed transcript seeking, manual editing, evidence sidecars, watch folders, resumable jobs, or a prebuilt installer. These are separate additions and are not necessary to make the basic file-to-text workflow useful.

## Acceptance checks

1. A representative `.m4a` produces one complete UTF-8 `.txt` with no app-added text.
2. Existing files and source audio remain unchanged, including output-name collisions and cancellation.
3. Invalid, empty, special-file, and excessive-duration inputs fail without a successful transcript.
4. Setup completes with explicit downloads; later transcription succeeds with outbound networking blocked. Static separation alone is not a network-isolation test.
5. GPU failure has a visible, bounded CPU retry in Auto; explicit CPU never requests GPU.
6. Review held-out excerpts containing Australian accents, names, numbers, hesitations, overlap, profanity, silence, and music. Record omission, insertion, and substitution errors against an independently checked reference.
7. Include opening and closing words, and several long episodes, in coverage checks. Do not infer long-file reliability from a short speech fixture.
8. Label results by model, exact engine revision, device, settings, and hardware. A tiny-model smoke test is not a quality benchmark for large-v3-turbo.

Primary dependency references and installation details are in [README.md](README.md).
