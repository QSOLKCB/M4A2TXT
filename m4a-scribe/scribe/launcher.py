"""Small desktop-first entry point shared by the checkout and portable package."""
import shutil
import sys

from . import __version__
from .__main__ import main as app_main
from .core import ROOT
from .desktop import PROFILES, executable, readiness


HELP = """M4A2TXT — local audio to plain text

Usage: ./m4a2txt [AUDIO ...]
       ./m4a2txt --check
       ./m4a2txt --version
       ./m4a2txt --cli [CLI OPTIONS] AUDIO ...

With no options, open the GTK desktop. Choose Laptop, Mid, or High,
add audio, and click Transcribe. Use the labelled Set up button once
to install the selected local model and engine.

--check    Check local dependencies without downloading or changing anything.
--cli      Use the batch CLI; add --help for its options.
--version  Print the application version.

If desktop dependencies are missing, run ./install-deps.sh once on Ubuntu.
"""


def check() -> int:
    print(f"M4A2TXT {__version__}")
    missing = []
    try:
        from .gui import Adw, Gtk
        gtk = (Gtk.get_major_version(), Gtk.get_minor_version())
        adw = (Adw.get_major_version(), Adw.get_minor_version())
        print(f"GTK {gtk[0]}.{gtk[1]} / libadwaita {adw[0]}.{adw[1]}")
        if gtk < (4, 10) or adw < (1, 4):
            missing.append("GTK 4.10+ and libadwaita 1.4+")
    except (ImportError, ValueError) as exc:
        missing.append(str(exc))
    if not shutil.which("ffmpeg"):
        missing.append("FFmpeg")
    else:
        print("FFmpeg: available")
    if not executable(ROOT / ".runtime/cpu/bin/whisper-cli"):
        for tool in ("git", "cmake", "c++"):
            if not shutil.which(tool):
                missing.append(tool + " (needed for first-time engine setup)")
    for profile in PROFILES.values():
        needs = readiness(profile)
        print(f"{profile.title}: " + ("set up " + ", ".join(needs) if needs else "ready"))
    if missing:
        print("\nMissing dependencies:\n- " + "\n- ".join(missing))
        print("\nOn Ubuntu 24.04+, run ./install-deps.sh, then try ./m4a2txt again.")
        return 2
    print("\nDesktop dependencies are ready. Launch ./m4a2txt in your desktop session.")
    return 0


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--help"], ["-h"]):
        print(HELP)
        return 0
    if args == ["--version"]:
        print(__version__)
        return 0
    if args == ["--check"]:
        return check()
    if args[:1] == ["--cli"]:
        return app_main(args[1:])
    return app_main(["--gui", *args])
