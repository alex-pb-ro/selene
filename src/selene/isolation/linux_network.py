"""Additional network restrictions layered over a container's default seccomp policy."""

import ctypes
import errno
import os
import platform
import sys
from pathlib import Path


class LinuxNetworkBoundary:
    """Prevent new network and filesystem-socket channels in this process and its children.

    This filter complements a private container network, mount and process namespace. It
    cannot revoke pre-existing descriptors: the trusted launcher must pass only stdio and
    close other descriptors before loading application code. Private Unix socket pairs
    remain available for event-loop wakeups. Unsupported hosts or filter failures abort.
    """

    class _Argument(ctypes.Structure):
        _fields_ = [
            ("arg", ctypes.c_uint),
            ("op", ctypes.c_int),
            ("datum_a", ctypes.c_uint64),
            ("datum_b", ctypes.c_uint64),
        ]

    _ALLOW = 0x7FFF0000
    _DENY = 0x00050000 | errno.EPERM
    _NOT_EQUAL = 1
    _UNIX_DOMAIN = 1

    @classmethod
    def enter(cls) -> None:
        """Validate the container launch and close inherited channels before applying the filter."""
        if sys.platform != "linux" or os.getuid() == 0:
            raise RuntimeError("The isolated image must run as a non-root Linux user")
        status = Path("/proc/self/status").read_text()
        if "NoNewPrivs:\t1" not in status or "Seccomp:\t2" not in status:
            raise RuntimeError("The isolated image requires Docker's seccomp and no-new-privileges options")
        for descriptor in os.listdir("/proc/self/fd"):
            if int(descriptor) > 2:
                try:
                    os.close(int(descriptor))
                except OSError as error:
                    if error.errno != errno.EBADF:
                        raise
        cls.apply()

    @classmethod
    def apply(cls) -> None:
        """Install an inherited, synchronized filter without replacing existing restrictions."""
        if sys.platform != "linux" or platform.machine() not in ("aarch64", "x86_64"):
            raise RuntimeError("The isolated network profile requires native Linux ARM64 or x86-64")

        # bind the stable libseccomp ABI with explicit pointer and argument types
        library = ctypes.CDLL("libseccomp.so.2")
        library.seccomp_init.argtypes = [ctypes.c_uint32]
        library.seccomp_init.restype = ctypes.c_void_p
        library.seccomp_release.argtypes = [ctypes.c_void_p]
        library.seccomp_release.restype = None
        library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
        library.seccomp_syscall_resolve_name.restype = ctypes.c_int
        library.seccomp_rule_add_array.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.POINTER(cls._Argument),
        ]
        library.seccomp_rule_add_array.restype = ctypes.c_int
        library.seccomp_attr_set.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32]
        library.seccomp_attr_set.restype = ctypes.c_int
        library.seccomp_load.argtypes = [ctypes.c_void_p]
        library.seccomp_load.restype = ctypes.c_int

        context = library.seccomp_init(cls._ALLOW)
        if not context:
            raise RuntimeError("Cannot allocate the isolated network filter")
        try:
            # require no-new-privileges and synchronize any existing threads
            cls._check(library.seccomp_attr_set(context, 3, 1), "require no-new-privileges")
            cls._check(library.seccomp_attr_set(context, 4, 1), "synchronize the filter")

            # deny external channels, descriptor passing and asynchronous syscall bypasses
            for name in ("connect", "bind", "sendmsg", "sendmmsg", "io_uring_setup", "pidfd_getfd"):
                cls._deny(library, context, name)
            for name in ("socket", "socketpair"):
                cls._deny(library, context, name, cls._Argument(0, cls._NOT_EQUAL, cls._UNIX_DOMAIN, 0))

            # retain ordinary writes to private socket pairs; disallow addressed datagrams
            cls._deny(library, context, "sendto", cls._Argument(4, cls._NOT_EQUAL, 0, 0))
            cls._check(library.seccomp_load(context), "load the isolated network filter")
        finally:
            library.seccomp_release(context)

    @classmethod
    def _deny(cls, library: ctypes.CDLL, context: int, name: str, argument: _Argument | None = None) -> None:
        syscall = library.seccomp_syscall_resolve_name(name.encode("ascii"))
        if syscall < 0:
            raise RuntimeError(f"The isolation runtime does not recognize required syscall {name}")
        arguments = ctypes.pointer(argument) if argument is not None else None
        count = int(argument is not None)
        cls._check(library.seccomp_rule_add_array(context, cls._DENY, syscall, count, arguments), f"restrict {name}")

    @staticmethod
    def _check(result: int, operation: str) -> None:
        if result < 0:
            raise OSError(-result, f"Cannot {operation}")
