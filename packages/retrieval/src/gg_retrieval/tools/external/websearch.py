"""Provider-abstracted web search.

Tavily is the live provider when its key is configured; without a key the
deterministic fake stands in (same philosophy as the LLM/embedding fakes), so
keyless deployments still exercise the full external-evidence path.
"""

from abc import ABC, abstractmethod
from typing import Any

from gg_common.settings import ExternalToolSettings

from gg_retrieval.tools.external.fetch import Fetcher, require_list
from gg_retrieval.tools.external.models import ExternalResult

_TAVILY = "https://api.tavily.com/search"


class WebSearchProvider(ABC):
    source: str

    @abstractmethod
    async def search(self, query: str, *, limit: int) -> tuple[dict[str, Any], ...]:
        """Rows of {"title", "url", "snippet"}."""


class TavilyWebSearchProvider(WebSearchProvider):
    source = "Tavily web search"

    def __init__(self, fetcher: Fetcher, api_key: str) -> None:
        self._fetcher = fetcher
        self._api_key = api_key

    async def search(self, query: str, *, limit: int) -> tuple[dict[str, Any], ...]:
        payload = {"api_key": self._api_key, "query": query, "max_results": limit}
        raw = await self._fetcher.post_json(_TAVILY, payload)
        results = require_list(raw, "results", "Tavily search response")
        return tuple(
            {
                "title": str(r.get("title", ""))[:200],
                "url": r.get("url", ""),
                "snippet": str(r.get("content", ""))[:400],
            }
            for r in results
            if isinstance(r, dict)
        )


class FakeWebSearchProvider(WebSearchProvider):
    source = "synthetic web search (offline)"

    async def search(self, query: str, *, limit: int) -> tuple[dict[str, Any], ...]:
        return (
            {
                "title": f"Synthetic search result for {query!r}",
                "url": "https://example.invalid/synthetic-result",
                "snippet": "Synthetic offline record: no live web search key is configured.",
            },
        )


class WebSearchTool:
    def __init__(self, provider: WebSearchProvider, settings: ExternalToolSettings) -> None:
        self._provider = provider
        self._settings = settings

    async def search(self, query: str) -> ExternalResult:
        rows = await self._provider.search(query, limit=self._settings.result_limit)
        return ExternalResult(
            tool="web_search",
            title=f"Web search results for {query!r}",
            source=self._provider.source,
            query=query,
            url=_TAVILY if isinstance(self._provider, TavilyWebSearchProvider) else "",
            columns=("title", "url", "snippet"),
            rows=rows,
        )


def build_web_search(
    fetcher: Fetcher, settings: ExternalToolSettings, api_key: str | None
) -> WebSearchTool:
    if api_key:
        return WebSearchTool(TavilyWebSearchProvider(fetcher, api_key), settings)
    return WebSearchTool(FakeWebSearchProvider(), settings)
