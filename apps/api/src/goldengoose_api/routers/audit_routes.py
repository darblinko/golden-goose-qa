"""Audit-prep endpoints: the check catalogue grouped into collections, and
the readiness report that runs those deterministic gates live."""

from fastapi import APIRouter, HTTPException, Request
from gg_retrieval.audit import (
    AUDIT_COLLECTIONS,
    CHECKS_BY_ID,
    AuditReport,
    advisory_note,
)

from goldengoose_api.auth import QaOrAdmin
from goldengoose_api.schemas import (
    AuditCheckOut,
    AuditCheckResultOut,
    AuditCollectionOut,
    AuditReportOut,
)

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/collections", response_model=list[AuditCollectionOut])
async def list_collections(user: QaOrAdmin) -> list[AuditCollectionOut]:
    return [
        AuditCollectionOut(
            collection_id=collection.collection_id,
            title=collection.title,
            description=collection.description,
            checks=[
                AuditCheckOut(
                    check_id=check.check_id,
                    title=check.title,
                    description=check.description,
                    kind=check.kind,
                    defect_kind=check.defect_kind,
                )
                for check_id in collection.check_ids
                if (check := CHECKS_BY_ID[check_id])
            ],
        )
        for collection in AUDIT_COLLECTIONS
    ]


@router.get("/report", response_model=AuditReportOut)
async def run_report(
    request: Request, user: QaOrAdmin, collection: str | None = None
) -> AuditReportOut:
    runner = request.app.state.audit_runner
    try:
        report: AuditReport = await runner.run(collection)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    advisory = await advisory_note(request.app.state.providers.llm, report)
    return AuditReportOut(
        collection_id=report.collection_id,
        summary=report.summary,
        advisory=advisory,
        results=[
            AuditCheckResultOut(
                check_id=result.check.check_id,
                title=result.check.title,
                kind=result.check.kind,
                defect_kind=result.check.defect_kind,
                status=result.status,
                columns=list(result.columns),
                rows=[dict(row) for row in result.rows],
                truncated=result.truncated,
                source=result.source,
                detail=result.detail,
            )
            for result in report.results
        ],
    )
