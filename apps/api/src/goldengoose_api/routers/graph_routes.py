"""Knowledge graph endpoints: the trace neighbourhood of one record, with the
provenance of every link, for the web app's Trace tab."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from goldengoose_api import graph_trace
from goldengoose_api.auth import QaOrAdmin
from goldengoose_api.schemas import TraceOut

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/trace", response_model=TraceOut)
async def trace_record(
    request: Request,
    user: QaOrAdmin,
    anchor: str,
    hops: Annotated[int, Query(ge=1, le=2)] = 2,
) -> TraceOut:
    try:
        parsed = graph_trace.parse_anchor(anchor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = await graph_trace.trace_subgraph(request.app.state.graph_driver, parsed, hops)
    if result is None:
        raise HTTPException(status_code=404, detail="anchor not found")
    return TraceOut.model_validate(result)
