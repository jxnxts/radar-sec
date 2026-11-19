"""Event fan-out to WebSocket clients.

Every event gets an increasing sequence number. A connecting client subscribes
first and receives the snapshot afterwards; that way no event is lost in
between, and the client uses the number to drop what the snapshot already has.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

# Event types published on /ws.
FILING_NEW = "filing.new"
SIGNAL_NEW = "signal.new"
PRICE_TICK = "price.tick"
SYSTEM_STATUS = "system.status"
RANKING_UPDATE = "ranking.update"
# A new event of an extra source (Form 144, 8-K, 13F, short data) for the tape.
MARKET_EVENT_NEW = "market_event.new"
# The server changed what the dashboard should show (replay jump, new reference data).
FEED_RESET = "feed.reset"


class Subscription:
    """A client's queue. If the client cannot keep up, it is flagged to reconnect."""

    def __init__(self, maxsize: int):
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self.lagging = False

    def offer(self, event: dict[str, Any]) -> None:
        if self.lagging:
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.lagging = True


class Hub:
    def __init__(self, *, history: int = 400, queue_size: int = 1000):
        self.boot_id = uuid.uuid4().hex[:10]
        self.seq = 0
        self._history: deque[dict[str, Any]] = deque(maxlen=history)
        self._subscriptions: set[Subscription] = set()
        self._queue_size = queue_size
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop | None) -> None:
        """Sets the server's event loop, so other threads can publish."""
        self._loop = loop

    @property
    def clients(self) -> int:
        return len(self._subscriptions)

    def subscribe(self) -> Subscription:
        subscription = Subscription(self._queue_size)
        self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        self._subscriptions.discard(subscription)

    def publish(self, event_type: str, data: Any) -> dict[str, Any]:
        """Publishes an event. Must be called on the event loop thread."""
        with self._lock:
            self.seq += 1
            event = {
                "type": event_type,
                "seq": self.seq,
                "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "data": data,
            }
            self._history.append(event)
        for subscription in list(self._subscriptions):
            subscription.offer(event)
        return event

    def publish_threadsafe(self, event_type: str, data: Any) -> None:
        """Publishes from any thread (collection runs outside the event loop)."""
        loop = self._loop
        if loop is None or loop.is_closed():
            self.publish(event_type, data)  # no server running (tests, shutdown)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self.publish(event_type, data)
        else:
            loop.call_soon_threadsafe(self.publish, event_type, data)

    def events_since(self, seq: int) -> list[dict[str, Any]] | None:
        """Events after `seq`, or None if the history no longer reaches that far back."""
        with self._lock:
            if seq > self.seq:
                return None
            if seq == self.seq:
                return []
            if not self._history or self._history[0]["seq"] > seq + 1:
                return None
            return [event for event in self._history if event["seq"] > seq]
