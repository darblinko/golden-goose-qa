"""Thread replay ACL: a stored restricted message is redacted for a role that
may no longer read it, and served intact to a role that may.

Exercised without a database: the owner lookup and message list are
monkeypatched to canned rows so the test isolates the one guarantee the read
path adds — restriction is re-decided against the caller's current role at
replay time, not trusted from write time."""

import pytest
from fastapi.testclient import TestClient
from goldengoose_api import threads
from goldengoose_api.auth import mint_dev_token
from goldengoose_api.main import create_app
from goldengoose_api.routers import thread_routes


class _NullSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _message(role, content, access_level, citations):
    return {
        "id": f"msg-{role}-{access_level}",
        "role": role,
        "content": content,
        "verdict": "grounded" if role == "assistant" else None,
        "citations": citations,
        "trace": [{"step": "generate"}],
        "access_level": access_level,
        "created_at": "2026-07-18T00:00:00+00:00",
    }


@pytest.fixture()
def harness(monkeypatch):
    app = create_app()
    settings = app.state.settings
    app.state.session_factory = lambda: _NullSession()

    async def fake_get_thread(session, *, thread_id, owner):
        return {
            "id": thread_id,
            "title": "t",
            "created_at": "2026-07-18T00:00:00+00:00",
            "updated_at": "2026-07-18T00:00:00+00:00",
        }

    stored = [
        _message("user", "What does complaint C-2025-0142 say?", "general", []),
        _message(
            "assistant",
            "The complaint narrative describes...",
            "restricted",
            [{"doc_key": "C-2025-0142", "doc_type": "complaint"}],
        ),
    ]

    async def fake_list_messages(session, *, thread_id):
        return stored

    monkeypatch.setattr(thread_routes.threads, "get_thread", fake_get_thread)
    monkeypatch.setattr(thread_routes.threads, "list_messages", fake_list_messages)

    def auth(role):
        token = mint_dev_token(settings, email=f"{role}@example.com", role=role)
        return {"Authorization": f"Bearer {token}"}

    return TestClient(app), auth


_THREAD_ID = "00000000-0000-0000-0000-000000000001"


def test_privileged_role_sees_restricted_message(harness):
    client, auth = harness
    response = client.get(f"/threads/{_THREAD_ID}", headers=auth("qa_user"))
    assert response.status_code == 200
    messages = response.json()["messages"]
    assistant = messages[1]
    assert assistant["redacted"] is False
    assert assistant["content"] == "The complaint narrative describes..."
    assert assistant["citations"]


def test_downgraded_role_gets_restricted_message_redacted(harness):
    client, auth = harness
    response = client.get(f"/threads/{_THREAD_ID}", headers=auth("auditor_readonly"))
    assert response.status_code == 200
    messages = response.json()["messages"]

    # The general user turn is untouched — its existence and its own text are
    # not secret.
    assert messages[0]["redacted"] is False
    assert messages[0]["content"] == "What does complaint C-2025-0142 say?"

    # The restricted assistant turn keeps its slot but withholds content,
    # citations, and trace.
    assistant = messages[1]
    assert assistant["redacted"] is True
    assert assistant["content"] == threads.REDACTED_NOTICE
    assert assistant["citations"] == []
    assert assistant["trace"] == []
    # Metadata that is not the restricted payload survives.
    assert assistant["access_level"] == "restricted"
    assert assistant["verdict"] == "grounded"
