# Tested Linux package

Download [M4A2TXT-0.2.0-preview-linux.tar.gz](M4A2TXT-0.2.0-preview-linux.tar.gz) and its [SHA-256 file](M4A2TXT-0.2.0-preview-linux.tar.gz.sha256).

```sh
sha256sum -c M4A2TXT-0.2.0-preview-linux.tar.gz.sha256
tar -xzf M4A2TXT-0.2.0-preview-linux.tar.gz
cd M4A2TXT-0.2.0-preview
./m4a2txt
```

If native dependencies are missing, run `./install-deps.sh` once, then `./m4a2txt` again. This package is for Ubuntu 24.04+ and uses the OS Python, GTK and FFmpeg. In the app, choose Laptop, Mid or High and use **Set up** once to install the selected model and build the local engine. Transcription is local after setup. See [full package instructions](../PACKAGING.md).

## Exact package identity

- Version: `0.2.0-preview`.
- Source commit: [`a7bacb14cdf775a972e45149a69cd5b76142cb60`](https://github.com/QSOLKCB/M4A2TXT/commit/a7bacb14cdf775a972e45149a69cd5b76142cb60).
- Archive SHA-256: `9207808572ee329e4032fa273b25b4f54f6af26ffa81b8687ee95143cdbd648f`.
- Validation date: 3 November 2026, Australia/Adelaide.

The checked-in archive is the exact file extracted and tested by [GitHub Actions run 41539974638](https://github.com/QSOLKCB/M4A2TXT/actions/runs/41539974638). An independent local rebuild of the same source commit produced identical archive and checksum bytes. `SOURCE_COMMIT.txt` and the full file manifest are inside the archive. This package receipt lives outside the archive so its evidence can refer to the final archive digest.

## Executed checks

| Check | Result |
| --- | --- |
| Packaging tests | 2 passed: deterministic roundtrip, executable launcher, spaces in installation paths, other working directories, checksum coverage, exclusions, rejected missing executable permission |
| Packaged app regression tests | 28 passed after extraction, including real FFmpeg decoding and controlled recognizer failure/cancellation cases |
| Packaged GTK test | Passed under Xvfb on Ubuntu 24.04: all three presets, initial setup state, file dropping, queue completion, transcript viewing, dialogs, cancellation, close |
| Packaged launcher | `./m4a2txt --version`, `--help`, `--cli --help`, and `--check` passed in their respective local/CI checks |
| Syntax and manifests | Passed for packaged Python, shell scripts, all shipped files, and the archive checksum |
| Real CPU M4A transcription | Passed through the extracted `m4a2txt --cli` executable, using relative input/output paths from another working directory |
| Offline CPU repeat | Passed through the packaged CLI harness with IPv4, IPv6, and Unix socket creation verified denied; repeat output identical |
| Input and output preservation | Source M4A unchanged; repeat run saved a second transcript without overwriting the first |

The real-engine check used the upstream JFK speech sample encoded to AAC/M4A, whisper.cpp `1.9.5`, and the separately installed `tiny.en` model. Its exact identities and results are in [cpu-package-smoke.json](cpu-package-smoke.json). It validates the runnable package's pipeline, not the recognition quality of the three larger preset models.

GPU compilation/inference, full-episode accuracy, and installation on the user's physical desktop remain unverified. Model weights, engine binaries, user audio, and system libraries are not bundled. No release tag or merge is implied by this downloadable preview.

To reproduce these archive bytes from the repository:

```sh
python3 scripts/package.py --ref a7bacb14cdf775a972e45149a69cd5b76142cb60 --output-dir dist
```
