"""Owned Compose process tree. This standalone helper imports only the standard library."""

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes


def _windows_job():
    """Contain this helper and every subsequently created child before launching Docker."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_working_set", ctypes.c_size_t),
            ("max_working_set", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "read_ops",
                "write_ops",
                "other_ops",
                "read_bytes",
                "write_bytes",
                "other_bytes",
            )
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io", IoCounters),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process", ctypes.c_size_t),
            ("peak_job", ctypes.c_size_t),
        ]

    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway permission.
    if not job or not kernel.SetInformationJobObject(
        job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
    ):
        raise OSError("Cannot configure the Compose process job.")
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise OSError("Cannot contain the Compose process tree.")
    # Do not close this handle while this helper is alive: it owns the job and
    # closes it through OS process teardown, killing any surviving descendants.
    return job


def main() -> int:
    if len(sys.argv) < 2:
        return 2
    try:
        job = _windows_job() if os.name == "nt" else None
        code = subprocess.call(
            sys.argv[1:],
            stdin=subprocess.DEVNULL,
            **({"creationflags": 0x08000000} if os.name == "nt" else {}),
        )
        # Keep the job handle alive through process teardown, including normal
        # exit when an executable has spawned a plugin that retained stdout.
        _ = job
        return code if code >= 0 else 1
    except OSError:
        print("Unable to start an isolated local Compose process tree.", flush=True)
        return 1


if __name__ == "__main__":
    os._exit(main())
