"""PTY-connected process-tree owner; standalone standard-library bootstrap."""

import ctypes
import json
import os
import signal
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


def _windows_job():
    # Assign the helper before spawning: descendants cannot escape on startup.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
            ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes"
        )]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits), ("io", IoCounters),
            ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
            ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t),
        ]

    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE, without breakaway.
    if not job or not kernel.SetInformationJobObject(
        job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
    ) or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise OSError("Unable to contain the Code process tree.")
    return job


def main():
    status = Path(sys.argv[1])
    result = {}
    try:
        job = _windows_job() if os.name == "nt" else None
        # Inherit all three PTY handles; never invoke an interactive shell.
        result["exit_code"] = subprocess.call(sys.argv[2:])
        _ = job  # Keep kill-on-close containment until helper process teardown.
    except OSError as error:
        result["error"] = str(error)
        print(f"Unable to run Code profile: {error}", flush=True)
    finally:
        status.write_text(json.dumps(result), encoding="utf-8")
        if os.name != "nt":
            # Includes orphan descendants even after the target itself exits.
            os.killpg(os.getpgrp(), signal.SIGKILL)
    return 0


if __name__ == "__main__":
    os._exit(main())
