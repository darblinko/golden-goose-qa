"""Bundle of all external tools sharing one cached, throttled fetcher.

Built once at app startup and handed to the agent as a single dependency, so
node code never assembles fetchers or juggles per-tool configuration.
"""

from dataclasses import dataclass

from gg_common.settings import ExternalToolSettings

from gg_retrieval.tools.external.clinicaltrials import ClinicalTrialsTool
from gg_retrieval.tools.external.ecfr import ECFRTool
from gg_retrieval.tools.external.fetch import build_fetcher
from gg_retrieval.tools.external.openfda import OpenFDATool
from gg_retrieval.tools.external.pubmed import PubMedTool
from gg_retrieval.tools.external.websearch import WebSearchTool, build_web_search


@dataclass(frozen=True)
class ExternalToolkit:
    openfda: OpenFDATool
    ecfr: ECFRTool
    clinicaltrials: ClinicalTrialsTool
    pubmed: PubMedTool
    websearch: WebSearchTool


def build_external_toolkit(
    settings: ExternalToolSettings, *, tavily_api_key: str | None = None
) -> ExternalToolkit:
    fetcher = build_fetcher(settings)
    return ExternalToolkit(
        openfda=OpenFDATool(fetcher, settings),
        ecfr=ECFRTool(fetcher, settings),
        clinicaltrials=ClinicalTrialsTool(fetcher, settings),
        pubmed=PubMedTool(fetcher, settings),
        websearch=build_web_search(fetcher, settings, tavily_api_key),
    )
