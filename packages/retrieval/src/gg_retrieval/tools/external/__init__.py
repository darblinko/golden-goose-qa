"""External regulatory data tools with typed external provenance."""

from gg_retrieval.tools.external.clinicaltrials import ClinicalTrialsTool
from gg_retrieval.tools.external.ecfr import ECFRTool
from gg_retrieval.tools.external.fetch import (
    CachingFetcher,
    ExternalFetchError,
    FakeFetcher,
    Fetcher,
    HttpxFetcher,
    build_fetcher,
)
from gg_retrieval.tools.external.models import ExternalResult
from gg_retrieval.tools.external.openfda import OpenFDATool
from gg_retrieval.tools.external.pubmed import PubMedTool
from gg_retrieval.tools.external.toolkit import ExternalToolkit, build_external_toolkit
from gg_retrieval.tools.external.websearch import (
    FakeWebSearchProvider,
    TavilyWebSearchProvider,
    WebSearchProvider,
    WebSearchTool,
    build_web_search,
)

__all__ = [
    "CachingFetcher",
    "ClinicalTrialsTool",
    "ECFRTool",
    "ExternalFetchError",
    "ExternalResult",
    "ExternalToolkit",
    "FakeFetcher",
    "FakeWebSearchProvider",
    "Fetcher",
    "HttpxFetcher",
    "OpenFDATool",
    "PubMedTool",
    "TavilyWebSearchProvider",
    "WebSearchProvider",
    "WebSearchTool",
    "build_external_toolkit",
    "build_fetcher",
    "build_web_search",
]
