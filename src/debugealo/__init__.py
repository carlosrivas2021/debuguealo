"""Primary debugealo package with identity-preserving debugpilot imports."""

from debugpilot import __version__

from ._compat import install_compat_imports

install_compat_imports()

__all__ = ["__version__"]
