"""openFDA device tools: MAUDE events, recalls, 510(k), PMA, GUDID, plus FDA
compliance actions (warning letters / injunctions) from the data dashboard.

Responses are mapped defensively — openFDA records are external data and any
field may be absent. The api_key never appears in the audit-trail URL.
"""

from typing import Any

from gg_common.settings import ExternalToolSettings

from gg_retrieval.tools.external.fetch import ExternalFetchError, Fetcher, require_list
from gg_retrieval.tools.external.models import ExternalResult

_OPENFDA = "https://api.fda.gov"
_DASHBOARD = "https://api-datadashboard.fda.gov/v1/compliance_actions"


class OpenFDATool:
    def __init__(self, fetcher: Fetcher, settings: ExternalToolSettings) -> None:
        self._fetcher = fetcher
        self._settings = settings

    async def maude_events(self, device_name: str) -> ExternalResult:
        results, total, url = await self._search(
            "/device/event.json", f'device.generic_name:"{device_name}"'
        )
        rows = tuple(_maude_row(r) for r in results)
        return self._result(
            "openfda_maude",
            f"MAUDE adverse event reports for {device_name!r}",
            "openFDA device/event API",
            device_name,
            url,
            ("report_number", "date_received", "event_type", "brand_name", "narrative"),
            rows,
            total=total,
        )

    async def recalls(self, device_name: str) -> ExternalResult:
        results, total, url = await self._search(
            "/device/enforcement.json", f'product_description:"{device_name}"'
        )
        rows = tuple(_recall_row(r) for r in results)
        return self._result(
            "openfda_recalls",
            f"Device recalls mentioning {device_name!r}",
            "openFDA device/enforcement API",
            device_name,
            url,
            ("recall_number", "classification", "status", "initiated", "firm", "reason"),
            rows,
            total=total,
        )

    async def clearances_510k(self, query: str) -> ExternalResult:
        results, total, url = await self._search(
            "/device/510k.json", f'device_name:"{query}" k_number:"{query}"'
        )
        rows = tuple(_510k_row(r) for r in results)
        return self._result(
            "openfda_510k",
            f"510(k) clearances for {query!r}",
            "openFDA device/510k API",
            query,
            url,
            ("k_number", "device_name", "applicant", "decision_date", "decision"),
            rows,
            total=total,
        )

    async def pma_approvals(self, query: str) -> ExternalResult:
        results, total, url = await self._search(
            "/device/pma.json", f'trade_name:"{query}" pma_number:"{query}"'
        )
        rows = tuple(_pma_row(r) for r in results)
        return self._result(
            "openfda_pma",
            f"PMA approvals for {query!r}",
            "openFDA device/pma API",
            query,
            url,
            ("pma_number", "supplement", "trade_name", "applicant", "decision_date"),
            rows,
            total=total,
        )

    async def gudid(self, query: str) -> ExternalResult:
        results, total, url = await self._search("/device/udi.json", f'brand_name:"{query}"')
        rows = tuple(_udi_row(r) for r in results)
        return self._result(
            "openfda_gudid",
            f"GUDID device records for {query!r}",
            "openFDA device/udi API",
            query,
            url,
            ("primary_di", "brand_name", "model", "company", "description"),
            rows,
            total=total,
        )

    async def compliance_actions(self, firm_name: str) -> ExternalResult:
        payload = {
            "filters": {"ProductType": ["Devices"], "LegalName": [firm_name]},
            "columns": ["LegalName", "ActionType", "ActionTakenDate", "State", "CaseInjunctionID"],
            "limit": self._settings.result_limit,
        }
        raw = await self._fetcher.post_json(_DASHBOARD, payload)
        results = [
            r
            for r in require_list(raw, "result", "FDA Data Dashboard response")
            if isinstance(r, dict)
        ]
        rows = tuple(_compliance_row(r) for r in results[: self._settings.result_limit])
        return self._result(
            "fda_compliance_actions",
            f"FDA compliance actions for {firm_name!r}",
            "FDA Data Dashboard compliance_actions API",
            firm_name,
            _DASHBOARD,
            ("firm", "action_type", "action_date", "state", "case_id"),
            rows,
            truncated=len(results) > self._settings.result_limit,
        )

    async def _search(
        self, endpoint: str, search: str
    ) -> tuple[list[dict[str, Any]], int | None, str]:
        url = f"{_OPENFDA}{endpoint}"
        audit_url = f"{url}?search={search}"
        params: dict[str, Any] = {"search": search, "limit": self._settings.result_limit}
        if self._settings.openfda_api_key is not None:
            params["api_key"] = self._settings.openfda_api_key.get_secret_value()
        try:
            raw = await self._fetcher.get_json(url, params)
        except ExternalFetchError as exc:
            # openFDA answers HTTP 404 NOT_FOUND for a well-formed query with
            # zero matches — a genuine empty result, not a failure.
            if exc.status_code == 404:
                return [], 0, audit_url
            raise
        results = require_list(raw, "results", f"openFDA {endpoint} response")
        return [r for r in results if isinstance(r, dict)], _meta_total(raw), audit_url

    def _result(
        self,
        tool: str,
        title: str,
        source: str,
        query: str,
        url: str,
        columns: tuple[str, ...],
        rows: tuple[dict[str, Any], ...],
        *,
        truncated: bool = False,
        total: int | None = None,
    ) -> ExternalResult:
        return ExternalResult(
            tool=tool,
            title=title,
            source=source,
            query=query,
            url=url,
            columns=columns,
            rows=rows,
            truncated=truncated,
            total=total,
        )


def _meta_total(raw: dict[str, Any]) -> int | None:
    """Read the authoritative match count from an openFDA ``meta.results.total``.

    The ``results`` array is one capped page; ``meta.results.total`` is the full
    count behind the query and the only sound basis for a rate. Anything that is
    not a non-negative, non-boolean integer is treated as absent (None) rather
    than trusted — external data, validated at the boundary.
    """
    meta = raw.get("meta")
    if not isinstance(meta, dict):
        return None
    results_meta = meta.get("results")
    if not isinstance(results_meta, dict):
        return None
    total = results_meta.get("total")
    if isinstance(total, bool) or not isinstance(total, int):
        return None
    if total < 0:
        return None
    return total


def _first_device(record: dict[str, Any]) -> dict[str, Any]:
    devices = record.get("device")
    if isinstance(devices, list) and devices and isinstance(devices[0], dict):
        return devices[0]
    return {}


def _narrative(record: dict[str, Any]) -> str:
    texts = record.get("mdr_text")
    if isinstance(texts, list):
        for entry in texts:
            if isinstance(entry, dict) and entry.get("text"):
                return str(entry["text"])[:400]
    return ""


def _maude_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_number": record.get("report_number", ""),
        "date_received": record.get("date_received", ""),
        "event_type": record.get("event_type", ""),
        "brand_name": _first_device(record).get("brand_name", ""),
        "narrative": _narrative(record),
    }


def _recall_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "recall_number": record.get("recall_number", ""),
        "classification": record.get("classification", ""),
        "status": record.get("status", ""),
        "initiated": record.get("recall_initiation_date", ""),
        "firm": record.get("recalling_firm", ""),
        "reason": str(record.get("reason_for_recall", ""))[:400],
    }


def _510k_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "k_number": record.get("k_number", ""),
        "device_name": record.get("device_name", ""),
        "applicant": record.get("applicant", ""),
        "decision_date": record.get("decision_date", ""),
        "decision": record.get("decision_description", record.get("decision_code", "")),
    }


def _pma_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "pma_number": record.get("pma_number", ""),
        "supplement": record.get("supplement_number", ""),
        "trade_name": record.get("trade_name", ""),
        "applicant": record.get("applicant", ""),
        "decision_date": record.get("decision_date", ""),
    }


def _udi_row(record: dict[str, Any]) -> dict[str, Any]:
    identifiers = record.get("identifiers")
    primary_di = ""
    if isinstance(identifiers, list) and identifiers and isinstance(identifiers[0], dict):
        primary_di = identifiers[0].get("id", "")
    return {
        "primary_di": primary_di,
        "brand_name": record.get("brand_name", ""),
        "model": record.get("version_or_model_number", ""),
        "company": record.get("company_name", ""),
        "description": str(record.get("device_description", ""))[:400],
    }


def _compliance_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "firm": record.get("LegalName", ""),
        "action_type": record.get("ActionType", ""),
        "action_date": record.get("ActionTakenDate", ""),
        "state": record.get("State", ""),
        "case_id": record.get("CaseInjunctionID", ""),
    }
