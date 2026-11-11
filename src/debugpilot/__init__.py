"""DebugPilot's UI-independent local debugging toolkit."""

from importlib.metadata import PackageNotFoundError, version

try:
    # pyproject.toml is the single source of truth; release-please bumps it.
    __version__ = version("debugealo")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"
