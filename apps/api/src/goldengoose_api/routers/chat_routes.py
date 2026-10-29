"""Chat over SSE.

POST /threads/{id}/messages streams the agent turn as named events:
    step       agent progress (route, retrieve, grade, rewrite, generate, verify)
    citations  citation panel payload, emitted once verified
    delta      answer text chunks
    done       persisted assistant message (id, verdict)
    error      terminal failure

The turn is durable before it is visible: the assistant message (with verdict,
citations, and step trace) and the audit event are committed in one transaction
BEFORE any `delta` text is streamed, so no answer content ever reaches a client
without a persisted, audited record behind it. A turn that fails mid-flight
writes a failure audit row before the `error` event.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from gg_agents.audit import build_turn_audit_event, build_turn_failure_audit_event
from gg_agents.state import AgentState, initial_state
from gg_common.audit import write_audit_event
from gg_common.costs import CostLedger, track_costs
from gg_common.tracing import set_span_attributes, span
from sse_starlette.sse import EventSourceResponse

from goldengoose_api import threads
from goldengoose_api.auth import CurrentUser
from goldengoose_api.schemas import MessageCreate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/threads", tags=["chat"])

_DELTA_CHARS = 64


def _sse(event: str, data: dict[str, Any]) -> dict[str, str]:
    return {"event": event, "data": json.dumps(data, default=str)}


def _deltas(answer: str) -> list[str]:
    return [answer[i : i + _DELTA_CHARS] for i in range(0, len(answer), _DELTA_CHARS)]


@router.post("/{thread_id}/messages")
async def post_message(
    request: Request,
    thread_id: uuid.UUID,
    body: MessageCreate,
    user: CurrentUser,
) -> EventSourceResponse:
    state = request.app.state
    tid = str(thread_id)
    async with state.session_factory() as session:
        thread = await threads.get_thread(session, thread_id=tid, owner=user.subject)
        if thread is None:
            raise HTTPException(status_code=404, detail="thread not found")
        history = await threads.recent_history(session, thread_id=tid, role=user.role)
        await threads.add_message(session, thread_id=tid, role="user", content=body.content)
        await session.commit()

    async def turn() -> AsyncIterator[dict[str, str]]:
        trace: list[dict[str, Any]] = []
        final: dict[str, Any] = {}
        with track_costs() as costs, span("chat.turn", thread=tid, role=user.role):
            async for event in _run_turn(trace, final, costs):
                yield event

    async def _run_turn(
        trace: list[dict[str, Any]], final: dict[str, Any], costs: CostLedger
    ) -> AsyncIterator[dict[str, str]]:
        try:
            config = {"configurable": {"thread_id": tid}}
            stream = state.agent_graph.astream(
                initial_state(body.content, history, role=user.role),
                config=config,
                stream_mode=["custom", "values"],
            )
            async for mode, payload in stream:
                if mode == "custom":
                    trace.append(payload)
                    event = "citations" if payload.get("event") == "citations" else "step"
                    yield _sse(event, payload)
                else:
                    final = payload

            answer = final.get("answer", "")
            # Durable before visible: commit the assistant message and audit
            # row first, so a client can never see answer text that has no
            # persisted record behind it.
            async with state.session_factory() as session:
                message = await threads.add_message(
                    session,
                    thread_id=tid,
                    role="assistant",
                    content=answer,
                    verdict=final.get("verdict"),
                    citations=final.get("citations", []),
                    trace=trace,
                )
                audit_event = build_turn_audit_event(
                    _as_state(final),
                    settings=state.settings,
                    thread_id=tid,
                    actor=user.subject,
                )
                await write_audit_event(session, audit_event)
                await session.commit()

            for delta in _deltas(answer):
                yield _sse("delta", {"text": delta})
            usage = costs.summary()
            set_span_attributes(
                verdict=final.get("verdict"),
                cost_usd=usage["cost_usd"],
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
            )
            logger.info(
                "chat turn thread=%s verdict=%s cost_usd=%.6f input_tokens=%d output_tokens=%d",
                tid,
                final.get("verdict"),
                usage["cost_usd"],
                usage["input_tokens"],
                usage["output_tokens"],
            )
            yield _sse(
                "done",
                {
                    "message_id": message["id"],
                    "verdict": final.get("verdict"),
                    "usage": usage,
                },
            )
        except Exception as exc:
            logger.exception("chat turn failed for thread %s", tid)
            set_span_attributes(error=True)
            # The failure itself is auditable. Best-effort: a database outage
            # here must not swallow the error event the client is owed.
            try:
                async with state.session_factory() as session:
                    await write_audit_event(
                        session,
                        build_turn_failure_audit_event(
                            body.content,
                            thread_id=tid,
                            actor=user.subject,
                            error=f"{type(exc).__name__}: {exc}",
                        ),
                    )
                    await session.commit()
            except Exception:
                logger.exception("failure audit write failed for thread %s", tid)
            yield _sse("error", {"detail": "the agent turn failed; see server logs"})

    return EventSourceResponse(turn(), headers={"Cache-Control": "no-cache, no-transform"})


def _as_state(final: dict[str, Any]) -> AgentState:
    return final  # type: ignore[return-value]  # graph output is the state dict
