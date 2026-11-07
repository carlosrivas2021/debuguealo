"""Pinned local Code-run ownership and retained terminal presentation state."""

from dataclasses import dataclass


@dataclass
class CodeRunContext:
    """One saved profile's local process, startup task, and terminal screen."""

    key: str
    profile: object
    screen: object
    stream: object
    session: object = None
    start_task: object = None
    generation: int = 0
    pending: bool = False
    active: bool = False
    stopping: bool = False
    state: str = ""
    close_task: object = None
