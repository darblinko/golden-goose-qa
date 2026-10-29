"""Full chat-turn proof through the API against live services: mint a dev
token, create a thread, POST a question, and assert the SSE contract
(step -> citations -> delta -> done), persistence of both messages, owner
isolation, and the per-turn audit row. The app lifespan itself is under test
here — it wires the retriever and the Postgres-checkpointed agent graph."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from gg_common.settings import get_settings
from goldengoose_api.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

QUESTION = "What does the CAPA procedure require before a CAPA can be closed?"


def _parse_sse(lines):
    events, name, data = [], None, []
    for line in lines:
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data.append(line.split(":", 1)[1].strip())
        elif not line.strip() and name is not None:
            events.append((name, json.loads("".join(data)) if data else {}))
            name, data = None, []
    return events


def _mint(client, email):
    response = client.post("/auth/dev-token", json={"email": email, "role": "qa_user"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_chat_turn_streams_and_persists(ingested_corpus):
    with TestClient(create_app()) as client:
        auth = _mint(client, "auditor@example.com")

        ready = client.get("/ready")
        assert ready.status_code == 200

        created = client.post("/threads", json={}, headers=auth)
        assert created.status_code == 201
        thread_id = created.json()["id"]

        with client.stream(
            "POST", f"/threads/{thread_id}/messages", json={"content": QUESTION}, headers=auth
        ) as response:
            assert response.status_code == 200
            events = _parse_sse(response.iter_lines())

        names = [name for name, _ in events]
        assert "step" in names
        assert "error" not in names, events

        done = [payload for name, payload in events if name == "done"]
        assert len(done) == 1, names
        assert done[0]["verdict"] == "grounded", events
        # R-16: the turn's cost/latency ledger surfaces in-band on the done
        # payload (per-turn observability; ADR-0017). Fakes report zero cost.
        usage = done[0]["usage"]
        assert {"cost_usd", "input_tokens", "output_tokens"} <= usage.keys(), done[0]

        citations = [payload for name, payload in events if name == "citations"]
        assert citations and citations[0]["items"], events

        answer = "".join(p["text"] for name, p in events if name == "delta")
        assert answer.strip()

        detail = client.get(f"/threads/{thread_id}", headers=auth)
        assert detail.status_code == 200
        messages = detail.json()["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[1]["content"] == answer
        assert messages[1]["verdict"] == "grounded"
        assert messages[1]["citations"]
        assert messages[1]["trace"]

        # The first turn titles the thread from the question.
        assert detail.json()["thread"]["title"] == QUESTION[:80]

        # Another owner sees 404, indistinguishable from a missing thread.
        other = _mint(client, "someone-else@example.com")
        assert client.get(f"/threads/{thread_id}", headers=other).status_code == 404
        assert (
            client.post(
                f"/threads/{thread_id}/messages", json={"content": "hi"}, headers=other
            ).status_code
            == 404
        )

    audit = asyncio.run(_latest_turn_audit())
    assert audit["actor"] == "auditor@example.com"
    payload = json.loads(audit["payload"])
    assert payload["thread_id"] == thread_id
    assert payload["verdict"] == "grounded"
    assert payload["cited"], payload


async def _latest_turn_audit():
    engine = create_async_engine(get_settings().postgres.sqlalchemy_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT actor, payload::text AS payload FROM audit.audit_log "
                        "WHERE action = 'chat.turn' ORDER BY id DESC LIMIT 1"
                    )
                )
            ).one()
            return {"actor": row.actor, "payload": row.payload}
    finally:
        await engine.dispose()
