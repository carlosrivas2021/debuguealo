"""Single-profile Python debugging backend; no UI or persistent configuration."""

from debugpilot.debugger.dap import DebugError
from debugpilot.debugger.python import PythonDebugSession

__all__ = ['DebugError', 'PythonDebugSession']
