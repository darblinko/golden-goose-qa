"""Thread CRUD. All routes require auth and are scoped to the token subject."""

import uuid

from fastapi import APIRouter, HTTPException, Request

from goldengoose_api import threads
from goldengoose_api.auth import CurrentUser
from goldengoose_api.schemas import MessageOut, ThreadCreate, ThreadDetail, ThreadOut

router = APIRouter(prefix="/threads", tags=["threads"])


@router.post("", response_model=ThreadOut, status_code=201)
async def create_thread(request: Request, body: ThreadCreate, user: CurrentUser) -> ThreadOut:
    async with request.app.state.session_factory() as session:
        thread = await threads.create_thread(session, owner=user.subject, title=body.title)
        await session.commit()
    return ThreadOut(**thread)


@router.get("", response_model=list[ThreadOut])
async def list_threads(request: Request, user: CurrentUser) -> list[ThreadOut]:
    async with request.app.state.session_factory() as session:
        rows = await threads.list_threads(session, owner=user.subject)
    return [ThreadOut(**row) for row in rows]


@router.get("/{thread_id}", response_model=ThreadDetail)
async def thread_detail(request: Request, thread_id: uuid.UUID, user: CurrentUser) -> ThreadDetail:
    async with request.app.state.session_factory() as session:
        thread = await threads.get_thread(session, thread_id=str(thread_id), owner=user.subject)
        if thread is None:
            raise HTTPException(status_code=404, detail="thread not found")
        messages = await threads.list_messages(session, thread_id=str(thread_id))
    # Re-authorize every stored message against the caller's current role: a
    # subject downgraded since the turn was written has its restricted messages
    # redacted on replay, not served from history.
    visible = [threads.redact_message_for_role(m, user.role) for m in messages]
    return ThreadDetail(thread=ThreadOut(**thread), messages=[MessageOut(**m) for m in visible])


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(request: Request, thread_id: uuid.UUID, user: CurrentUser) -> None:
    async with request.app.state.session_factory() as session:
        deleted = await threads.delete_thread(session, thread_id=str(thread_id), owner=user.subject)
        await session.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="thread not found")
