"""Event hub: sequence, history and slow clients."""

import asyncio

from radar.api.hub import Hub


def test_events_get_increasing_sequence_and_reach_subscribers():
    hub = Hub()
    first, second = hub.subscribe(), hub.subscribe()

    hub.publish("signal.new", {"id": "a"})
    event = hub.publish("filing.new", {"id": "b"})

    assert event["seq"] == 2 and hub.seq == 2
    assert [first.queue.get_nowait()["seq"] for _ in range(2)] == [1, 2]
    assert second.queue.qsize() == 2
    assert event["type"] == "filing.new" and event["data"] == {"id": "b"} and event["ts"]


def test_unsubscribed_client_stops_receiving():
    hub = Hub()
    subscription = hub.subscribe()
    hub.unsubscribe(subscription)
    hub.publish("signal.new", {})
    assert subscription.queue.empty() and hub.clients == 0


def test_slow_client_is_flagged_instead_of_blocking_the_others():
    hub = Hub(queue_size=2)
    slow, healthy = hub.subscribe(), hub.subscribe()
    for index in range(3):
        hub.publish("price.tick", {"n": index})
        healthy.queue.get_nowait()

    assert slow.lagging is True  # the server drops it; the client reconnects with a snapshot
    assert healthy.lagging is False and hub.seq == 3


def test_events_since_returns_the_gap_or_none_when_too_old():
    hub = Hub(history=3)
    for index in range(5):
        hub.publish("price.tick", {"n": index})

    assert hub.events_since(5) == []
    assert [e["seq"] for e in hub.events_since(3)] == [4, 5]
    assert hub.events_since(1) is None  # already gone from the history: only a snapshot helps
    assert hub.events_since(99) is None  # the server restarted and the count went back


def test_publish_from_another_thread_lands_on_the_loop():
    async def scenario():
        hub = Hub()
        hub.bind(asyncio.get_running_loop())
        subscription = hub.subscribe()
        await asyncio.to_thread(hub.publish_threadsafe, "signal.new", {"id": "x"})
        return await asyncio.wait_for(subscription.queue.get(), timeout=1)

    event = asyncio.run(scenario())
    assert event["data"] == {"id": "x"} and event["seq"] == 1
