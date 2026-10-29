"""Request/response models. All user input crosses these boundaries."""

from typing import Any

from pydantic import BaseModel, Field


class DevTokenRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str = Field(default="qa_user", pattern=r"^(admin|qa_user|auditor_readonly)$")


class DevTokenResponse(BaseModel):
    token: str


class ThreadCreate(BaseModel):
    title: str = Field(default="", max_length=200)


class ThreadOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    verdict: str | None
    citations: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    access_level: str
    redacted: bool = False
    created_at: str


class ThreadDetail(BaseModel):
    thread: ThreadOut
    messages: list[MessageOut]


class AuditCheckOut(BaseModel):
    check_id: str
    title: str
    description: str
    kind: str
    defect_kind: str | None


class AuditCollectionOut(BaseModel):
    collection_id: str
    title: str
    description: str
    checks: list[AuditCheckOut]


class AuditCheckResultOut(BaseModel):
    check_id: str
    title: str
    kind: str
    defect_kind: str | None
    status: str
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool
    source: str
    detail: str


class AuditReportOut(BaseModel):
    collection_id: str | None
    summary: str
    advisory: str
    results: list[AuditCheckResultOut]
