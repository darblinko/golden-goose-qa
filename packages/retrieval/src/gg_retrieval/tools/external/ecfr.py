"""eCFR regulation search and FDA guidance document lookup.

Both are keyless public endpoints. Guidance search filters the FDA's static
guidance-document JSON client-side — the caching fetcher makes the one large
fetch per TTL acceptable.
"""

import re
from typing import Any

from gg_common.settings import ExternalToolSettings

from gg_retrieval.tools.external.fetch import (
    Fetcher,
    MalformedExternalResponseError,
    require_list,
)
from gg_retrieval.tools.external.models import ExternalResult

_ECFR_SEARCH = "https://www.ecfr.gov/api/search/v1/results"
_FDA_GUIDANCE = "https://www.fda.gov/files/api/datatables/static/search-for-guidance.json"
_TAG_RE = re.compile(r"<[^>]+>")


class ECFRTool:
    def __init__(self, fetcher: Fetcher, settings: ExternalToolSettings) -> None:
        self._fetcher = fetcher
        self._settings = settings

    async def search_regulations(self, query: str) -> ExternalResult:
        params = {"query": query, "per_page": self._settings.result_limit}
        raw = await self._fetcher.get_json(_ECFR_SEARCH, params)
        results = require_list(raw, "results", "eCFR search response")
        rows = tuple(_regulation_row(r) for r in results if isinstance(r, dict))
        return ExternalResult(
            tool="ecfr_search",
            title=f"CFR sections matching {query!r}",
            source="eCFR search API",
            query=query,
            url=f"{_ECFR_SEARCH}?query={query}",
            columns=("citation", "heading", "excerpt", "current_as_of"),
            rows=rows,
        )

    async def guidance_documents(self, query: str) -> ExternalResult:
        raw = await self._fetcher.get_json(_FDA_GUIDANCE, {})
        documents = _guidance_list(raw)
        needle = query.lower()
        matched = [d for d in documents if needle in _strip_tags(str(d.get("title", ""))).lower()]
        rows = tuple(_guidance_row(d) for d in matched[: self._settings.result_limit])
        return ExternalResult(
            tool="fda_guidance",
            title=f"FDA guidance documents matching {query!r}",
            source="FDA guidance document index",
            query=query,
            url=_FDA_GUIDANCE,
            columns=("title", "issued", "center", "docket"),
            rows=rows,
            truncated=len(matched) > self._settings.result_limit,
        )


def _guidance_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        entries = raw["data"]
    elif isinstance(raw, list):
        entries = raw
    else:
        raise MalformedExternalResponseError(
            "FDA guidance index response is neither a data-keyed object nor a list"
        )
    return [e for e in entries if isinstance(e, dict)]


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text).strip()


def _regulation_row(record: dict[str, Any]) -> dict[str, Any]:
    hierarchy = record.get("hierarchy") or {}
    headings = record.get("headings") or {}
    title = hierarchy.get("title", "")
    section = hierarchy.get("section") or hierarchy.get("part", "")
    return {
        "citation": f"{title} CFR {section}".strip(),
        "heading": headings.get("section") or headings.get("part", ""),
        "excerpt": _strip_tags(str(record.get("full_text_excerpt", "")))[:400],
        "current_as_of": record.get("starts_on", ""),
    }


def _guidance_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _strip_tags(str(record.get("title", "")))[:200],
        "issued": record.get("field_issue_datetime", ""),
        "center": _strip_tags(str(record.get("field_center", ""))),
        "docket": record.get("field_docket_number", ""),
    }
