from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass

from apps.api.schemas import RunEventRecord


TERMINAL_EVENTS = {"run_completed", "run_failed", "run_cancelled"}


@dataclass(frozen=True)
class Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[RunEventRecord]


class SSEBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[Subscriber]] = defaultdict(set)

    def subscribe(self, run_id: str) -> Subscriber:
        subscriber = Subscriber(loop=asyncio.get_running_loop(), queue=asyncio.Queue())
        self._subscribers[run_id].add(subscriber)
        return subscriber

    def unsubscribe(self, run_id: str, subscriber: Subscriber) -> None:
        subscribers = self._subscribers.get(run_id)
        if not subscribers:
            return
        subscribers.discard(subscriber)
        if not subscribers:
            self._subscribers.pop(run_id, None)

    def publish(self, event: RunEventRecord) -> None:
        for subscriber in list(self._subscribers.get(event.run_id, set())):
            subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, event)
