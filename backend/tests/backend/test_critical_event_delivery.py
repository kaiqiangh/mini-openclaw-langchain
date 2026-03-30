"""Tests for critical event delivery in chat streaming."""
import asyncio
import pytest


@pytest.mark.asyncio
async def test_critical_events_not_dropped_on_full_queue():
    """done and error events must not be silently dropped when queue is full."""
    from api.chat import _StreamRunState, _publish_event

    state = _StreamRunState(
        key="test:session",
        agent_id="test",
        session_id="session",
        message="test",
    )

    # Create a small queue and fill it
    queue = asyncio.Queue(maxsize=2)
    state.subscribers.add(queue)

    # Fill the queue to capacity
    await queue.put({"fill": "1"})
    await queue.put({"fill": "2"})

    # Publish a critical 'done' event
    await _publish_event(state, "done", {"status": "complete"})

    # Drain the queue
    items = []
    while not queue.empty():
        try:
            items.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break

    # At least one 'done' event must be present
    done_events = [i for i in items if i and i.get("event") == "done"]
    assert len(done_events) >= 1, (
        f"done event must be delivered even on full queue, got: {items}"
    )


@pytest.mark.asyncio
async def test_error_event_delivery_guaranteed():
    """error events must be delivered even when queue is full."""
    from api.chat import _StreamRunState, _publish_event

    state = _StreamRunState(
        key="test:error-session",
        agent_id="test",
        session_id="error-session",
        message="test",
    )

    queue = asyncio.Queue(maxsize=1)
    state.subscribers.add(queue)

    # Fill the queue
    await queue.put({"fill": "1"})

    # Publish error event
    await _publish_event(state, "error", {"error": "something failed"})

    items = []
    while not queue.empty():
        try:
            items.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break

    error_events = [i for i in items if i and i.get("event") == "error"]
    assert len(error_events) >= 1, (
        f"error event must be delivered, got: {items}"
    )
