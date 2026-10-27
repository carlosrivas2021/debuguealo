"""Safe, user-facing failures; never wrap raw SDK/configuration values."""


class DebugPilotError(Exception):
    """Base application error."""


class ConfigurationError(DebugPilotError):
    """Configuration could not be read or validated."""


class LifecycleError(DebugPilotError):
    """An engine operation is incompatible with its lifecycle."""
