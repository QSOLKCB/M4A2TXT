#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$root"
# Ubuntu's GI bindings belong to its system Python, not an activated venv.
scribe_python=${SCRIBE_PYTHON:-/usr/bin/python3}
exec "$scribe_python" -m scribe --gui "$@"
