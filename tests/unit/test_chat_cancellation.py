"""A chat turn cancelled by a client disconnect is still audited: the turn's
start is recorded with the user message, and the cancellation is finalized
by shielded cleanup, because CancelledError bypasses `except Exception`."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from gg_common.settings import AppSettings
from goldengoose_api import threads
from goldengoose_api.routers import chat_routes
from goldengoose_api.schemas import MessageCreate


class _NullSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        return None


class _BlockingGraph:
    """Emits one step, then waits until the turn is cancelled."""

    def __init__(self):
        self.started = asyncio.Event()

    async def astream(self, *args, **kwargs):
        yield "custom", {"event": "step", "node": "route"}
        self.started.set()
        await asyncio.Event().wait()


@pytest.fixture()
def recorded(monkeypatch):
    actions: list[tuple[str, dict]] = []

    async def fake_get_thread(session, *, thread_id, owner):
        return {"id": thread_id}

    async def fake_recent_history(session, *, thread_id, role):
        return []

    async def fake_add_message(session, **kwargs):
        return {"id": "msg-1"}

    async def fake_write_audit_event(session, event):
        actions.append((event.action, event.payload))

    monkeypatch.setattr(threads, "get_thread", fake_get_thread)
    monkeypatch.setattr(threads, "recent_history", fake_recent_history)
    monkeypatch.setattr(threads, "add_message", fake_add_message)
    monkeypatch.setattr(chat_routes, "write_audit_event", fake_write_audit_event)
    return actions


async def test_disconnect_during_the_agent_run_is_audited(recorded):
    graph = _BlockingGraph()
    state = SimpleNamespace(session_factory=_NullSession, agent_graph=graph, settings=AppSettings())
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    user = SimpleNamespace(subject="user@example.test", role="qa_user")
    response = await chat_routes.post_message(
        request, uuid.uuid4(), MessageCreate(content="What does SOP-004 require?"), user
    )
    assert [action for action, _ in recorded] == ["chat.turn.started"]

    seen: list[dict] = []

    async def consume():
        # One task drives the stream, as the SSE response does.
        async for event in response.body_iterator:
            seen.append(event)

    pending = asyncio.create_task(consume())
    await graph.started.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert [event["event"] for event in seen] == ["step"]
    assert [action for action, _ in recorded] == ["chat.turn.started", "chat.turn.failed"]
    failure = recorded[1][1]
    assert failure["question"] == "What does SOP-004 require?"
    assert failure["error"].startswith("cancelled")
