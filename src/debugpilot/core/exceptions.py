"""Safe, user-facing failures; never wrap raw SDK/configuration values."""


class DebugPilotError(Exception):
    """Base application error."""


class ConfigurationError(DebugPilotError):
    """Configuration could not be read or validated."""


class LifecycleError(DebugPilotError):
    """An engine operation is incompatible with its lifecycle."""


class DockerError(DebugPilotError):
    """Safe Docker failure; retries must be explicitly permitted."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable
