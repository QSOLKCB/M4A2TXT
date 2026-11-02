"""Manual Linux smoke harness: deny new sockets, then run the real CLI.

Usage: python3 tests/offline_smoke.py [normal scribe CLI arguments]
Requires the system libseccomp runtime. This harness changes only its own
process tree. It is a test harness, not a sandbox for hostile executables.
"""
import ctypes
import errno
import os
from pathlib import Path
import socket
import sys


def main():
    library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_load.restype = ctypes.c_int
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("Cannot initialize seccomp")
    try:
        for name in (b"socket", b"socketpair", b"connect", b"bind", b"listen", b"accept", b"accept4"):
            number = library.seccomp_syscall_resolve_name(name)
            if number >= 0 and library.seccomp_rule_add(context, 0x00050000 | errno.EACCES, number, 0) != 0:
                raise RuntimeError(f"Cannot install socket denial rule: {name}")
        if library.seccomp_load(context) != 0:
            raise RuntimeError("Kernel refused the network-denial filter")
    finally:
        library.seccomp_release(context)
    for family in (socket.AF_INET, socket.AF_INET6, socket.AF_UNIX):
        try:
            with socket.socket(family, socket.SOCK_STREAM):
                raise RuntimeError("Socket denial did not take effect")
        except PermissionError:
            pass
    print("Socket-denial filter verified; running local transcription.", file=sys.stderr, flush=True)
    os.chdir(Path(__file__).resolve().parents[1])
    os.execv(sys.executable, [sys.executable, "-m", "scribe", *sys.argv[1:]])


if __name__ == "__main__":
    main()
