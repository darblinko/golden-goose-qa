"""Message-level access control against the live database: a message's access
level is computed from its citations, persisted by the 0010 migration's column,
read back, and re-decided against the caller's role on replay. Deterministic —
messages are inserted directly, so no agent turn or retrieval is involved."""

import uuid

import pytest
from goldengoose_api import threads
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.integration


async def test_access_level_persisted_and_redacted_on_replay(app_engine):
    session_factory = async_sessionmaker(app_engine, expire_on_commit=False)
    owner = f"replay-{uuid.uuid4()}@example.com"

    async with session_factory() as session:
        thread = await threads.create_thread(session, owner=owner, title="")
        tid = thread["id"]
        await threads.add_message(
            session, thread_id=tid, role="user", content="Ask about a complaint", citations=[]
        )
        await threads.add_message(
            session,
            thread_id=tid,
            role="assistant",
            content="The complaint narrative describes a device malfunction.",
            verdict="grounded",
            citations=[{"doc_key": "C-2025-0142", "doc_type": "complaint"}],
            trace=[{"step": "generate"}],
        )
        await session.commit()

        try:
            messages = await threads.list_messages(session, thread_id=tid)
            by_role = {m["role"]: m for m in messages}

            # The migration column stored the computed level: the user turn is
            # general, the complaint-cited assistant turn is restricted.
            assert by_role["user"]["access_level"] == "general"
            assert by_role["assistant"]["access_level"] == "restricted"

            # A privileged reader sees the restricted turn intact.
            qa_view = [threads.redact_message_for_role(m, "qa_user") for m in messages]
            assert all(not m["redacted"] for m in qa_view)

            # A downgraded reader has the restricted turn withheld but keeps the
            # general one.
            auditor_view = {
                m["role"]: threads.redact_message_for_role(m, "auditor_readonly") for m in messages
            }
            assert auditor_view["user"]["redacted"] is False
            assert auditor_view["assistant"]["redacted"] is True
            assert auditor_view["assistant"]["content"] == threads.REDACTED_NOTICE
            assert auditor_view["assistant"]["citations"] == []

            # recent_history feeds the agent only what the role may read, so a
            # downgraded caller's own restricted turn cannot re-enter the prompt.
            auditor_history = await threads.recent_history(
                session, thread_id=tid, role="auditor_readonly"
            )
            assert all("complaint narrative" not in h["content"] for h in auditor_history)
            qa_history = await threads.recent_history(session, thread_id=tid, role="qa_user")
            assert any("complaint narrative" in h["content"] for h in qa_history)
        finally:
            await threads.delete_thread(session, thread_id=tid, owner=owner)
            await session.commit()
