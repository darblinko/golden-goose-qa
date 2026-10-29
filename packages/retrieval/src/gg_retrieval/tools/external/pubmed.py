"""PubMed literature search via NCBI E-utilities (esearch + esummary)."""

from typing import Any

from gg_common.settings import ExternalToolSettings

from gg_retrieval.tools.external.fetch import (
    Fetcher,
    MalformedExternalResponseError,
    require_list,
)
from gg_retrieval.tools.external.models import ExternalResult

_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


class PubMedTool:
    def __init__(self, fetcher: Fetcher, settings: ExternalToolSettings) -> None:
        self._fetcher = fetcher
        self._settings = settings

    async def search(self, term: str) -> ExternalResult:
        ids = await self._search_ids(term)
        rows = await self._summaries(ids) if ids else ()
        return ExternalResult(
            tool="pubmed_search",
            title=f"PubMed articles matching {term!r}",
            source="NCBI PubMed E-utilities",
            query=term,
            url=f"{_ESEARCH}?db=pubmed&term={term}",
            columns=("pmid", "title", "journal", "published", "first_author"),
            rows=rows,
        )

    async def _search_ids(self, term: str) -> list[str]:
        params = {
            "db": "pubmed",
            "term": term,
            "retmode": "json",
            "retmax": self._settings.result_limit,
        }
        raw = await self._fetcher.get_json(_ESEARCH, params)
        if not isinstance(raw, dict) or not isinstance(raw.get("esearchresult"), dict):
            raise MalformedExternalResponseError(
                "PubMed esearch response has no esearchresult object"
            )
        ids = require_list(raw["esearchresult"], "idlist", "PubMed esearch response")
        return [str(i) for i in ids]

    async def _summaries(self, ids: list[str]) -> tuple[dict[str, Any], ...]:
        params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
        raw = await self._fetcher.get_json(_ESUMMARY, params)
        if not isinstance(raw, dict) or not isinstance(raw.get("result"), dict):
            raise MalformedExternalResponseError("PubMed esummary response has no result object")
        result = raw["result"]
        rows = []
        for pmid in ids:
            record = result.get(pmid)
            if isinstance(record, dict):
                rows.append(_article_row(pmid, record))
        return tuple(rows)


def _article_row(pmid: str, record: dict[str, Any]) -> dict[str, Any]:
    authors = record.get("authors")
    first_author = ""
    if isinstance(authors, list) and authors and isinstance(authors[0], dict):
        first_author = authors[0].get("name", "")
    return {
        "pmid": pmid,
        "title": str(record.get("title", ""))[:200],
        "journal": record.get("source", ""),
        "published": record.get("pubdate", ""),
        "first_author": first_author,
    }
