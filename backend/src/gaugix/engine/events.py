"""In-process pub/sub for live run progress (ARCHITECTURE §5).

No broker: one asyncio.Queue per subscriber, and events carry a monotonic `seq`
so the UI can drop anything that arrives out of order after a reconnect. The UI
always fetches full state first and *then* subscribes, so nothing is replayed —
events are strictly deltas.

Slow subscribers are dropped from their oldest event rather than allowed to
stall the engine: a browser tab that stops reading must never block a run.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from gaugix.config import redact_for_display
from gaugix.logging_setup import get_logger

log = get_logger("gaugix.events")

QUEUE_MAXSIZE = 512


class EventType(StrEnum):
    run_status = "run_status"
    item_status = "item_status"
    usage_delta = "usage_delta"
    log = "log"


@dataclass(slots=True)
class Event:
    type: EventType
    run_id: int
    data: dict[str, Any] = field(default_factory=dict)
    seq: int = 0

    def to_sse(self) -> dict[str, Any]:
        return {
            "event": str(self.type),
            "data": redact_for_display({**self.data, "seq": self.seq}),
        }


class EventBus:
    """Fan-out of run events to any number of subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[Event]]] = {}
        self._seq = itertools.count(1)

    def publish(self, event: Event) -> None:
        """Emit an event. Never blocks, never raises."""
        event.seq = next(self._seq)
        for queue in list(self._subscribers.get(event.run_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop the oldest so a stalled tab cannot back-pressure the engine.
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover
                    log.warning("event_dropped", run_id=event.run_id, type=str(event.type))

    def emit(self, type_: EventType, run_id: int, **data: Any) -> None:
        self.publish(Event(type=type_, run_id=run_id, data=data))

    def subscribe(self, run_id: int) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def unsubscribe(self, run_id: int, queue: asyncio.Queue[Event]) -> None:
        subscribers = self._subscribers.get(run_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(run_id, None)

    def subscriber_count(self, run_id: int) -> int:
        return len(self._subscribers.get(run_id, ()))

    async def stream(self, run_id: int) -> AsyncIterator[Event]:
        """Async iterator over a run's events. Cancel the task to stop."""
        queue = self.subscribe(run_id)
        try:
            while True:
                yield await queue.get()
        finally:
            self.unsubscribe(run_id, queue)

    def reset(self) -> None:
        """Drop all subscribers (tests)."""
        self._subscribers.clear()


#: Process-wide bus. The engine runs in the API process (ARCHITECTURE §5).
bus = EventBus()
