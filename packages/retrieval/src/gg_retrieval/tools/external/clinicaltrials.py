"""ClinicalTrials.gov v2 study search."""

from typing import Any

from gg_common.settings import ExternalToolSettings

from gg_retrieval.tools.external.fetch import Fetcher, require_list
from gg_retrieval.tools.external.models import ExternalResult

_STUDIES = "https://clinicaltrials.gov/api/v2/studies"


class ClinicalTrialsTool:
    def __init__(self, fetcher: Fetcher, settings: ExternalToolSettings) -> None:
        self._fetcher = fetcher
        self._settings = settings

    async def search(self, term: str) -> ExternalResult:
        params = {"query.term": term, "pageSize": self._settings.result_limit}
        raw = await self._fetcher.get_json(_STUDIES, params)
        studies = require_list(raw, "studies", "ClinicalTrials.gov response")
        rows = tuple(_study_row(s) for s in studies if isinstance(s, dict))
        return ExternalResult(
            tool="clinicaltrials_search",
            title=f"ClinicalTrials.gov studies matching {term!r}",
            source="ClinicalTrials.gov v2 API",
            query=term,
            url=f"{_STUDIES}?query.term={term}",
            columns=("nct_id", "title", "status", "study_type", "sponsor"),
            rows=rows,
        )


def _study_row(study: dict[str, Any]) -> dict[str, Any]:
    protocol = study.get("protocolSection") or {}
    identification = protocol.get("identificationModule") or {}
    status = protocol.get("statusModule") or {}
    design = protocol.get("designModule") or {}
    sponsor = (protocol.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}
    return {
        "nct_id": identification.get("nctId", ""),
        "title": str(identification.get("briefTitle", ""))[:200],
        "status": status.get("overallStatus", ""),
        "study_type": design.get("studyType", ""),
        "sponsor": sponsor.get("name", ""),
    }
