import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import BaseModel, ConfigDict, Field


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str = Field(max_length=80)
    message: str = Field(max_length=1000)


class Subscription:
    def __init__(self, capacity: int):
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=capacity)
        self.dropped = 0

    async def get(self) -> Event:
        return await self._queue.get()

    def _offer(self, event: Event) -> None:
        if self._queue.full():
            self._queue.get_nowait()
            self.dropped += 1
        self._queue.put_nowait(event)


class EventBus:
    """Bounded, nonblocking, single-event-loop fanout with drop-oldest backpressure.

    Consumers own cancellation of pending get() calls. Subscriptions are scoped;
    engine-owned consumers are canceled before the engine finishes closing.
    """

    def __init__(self, capacity: int = 256):
        if not 1 <= capacity <= 10_000:
            raise ValueError("Event capacity must be between 1 and 10000.")
        self._capacity = capacity
        self._subscriptions: set[Subscription] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[Subscription]:
        subscription = Subscription(self._capacity)
        self._subscriptions.add(subscription)
        try:
            yield subscription
        finally:
            self._subscriptions.discard(subscription)

    def publish(self, event: Event) -> None:
        for subscription in self._subscriptions:
            subscription._offer(event)
