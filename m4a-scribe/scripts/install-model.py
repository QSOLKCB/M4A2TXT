#!/usr/bin/env python3
"""Compatibility entry point for the explicit model installer."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scribe.models import *  # Preserve the script's importable setup API.

if __name__ == "__main__":
    raise SystemExit(command_line())
