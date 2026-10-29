"""External tool framework: fetcher caching/throttling, openFDA mapping,
and the provenance typing that keeps external evidence out of QMS citations."""

import asyncio

import httpx
import pytest
from gg_common.settings import ExternalToolSettings
from gg_retrieval.tools.external.clinicaltrials import ClinicalTrialsTool
from gg_retrieval.tools.external.ecfr import ECFRTool
from gg_retrieval.tools.external.fakes import offline_fetcher
from gg_retrieval.tools.external.fetch import (
    CachingFetcher,
    ExternalFetchError,
    FakeFetcher,
    Fetcher,
    HttpxFetcher,
    MalformedExternalResponseError,
    _safe_url,
    build_fetcher,
)
from gg_retrieval.tools.external.openfda import OpenFDATool
from gg_retrieval.tools.external.pubmed import PubMedTool
from gg_retrieval.tools.external.websearch import (
    FakeWebSearchProvider,
    TavilyWebSearchProvider,
    WebSearchTool,
    build_web_search,
)
from pydantic import SecretStr


def _settings(**overrides):
    return ExternalToolSettings(**overrides)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class TestCachingFetcher:
    async def test_caches_within_ttl_and_expires_after(self):
        inner = FakeFetcher((("api.test", {"value": 1}),))
        clock = _Clock()
        fetcher = CachingFetcher(
            inner, ttl_seconds=100.0, min_interval_seconds=0.0, time_fn=clock.time
        )
        await fetcher.get_json("https://api.test/x", {"q": "a"})
        await fetcher.get_json("https://api.test/x", {"q": "a"})
        assert len(inner.requests) == 1
        clock.now = 101.0
        await fetcher.get_json("https://api.test/x", {"q": "a"})
        assert len(inner.requests) == 2

    async def test_distinct_params_are_distinct_cache_entries(self):
        inner = FakeFetcher((("api.test", {"value": 1}),))
        fetcher = CachingFetcher(inner, min_interval_seconds=0.0, time_fn=_Clock().time)
        await fetcher.get_json("https://api.test/x", {"q": "a"})
        await fetcher.get_json("https://api.test/x", {"q": "b"})
        assert len(inner.requests) == 2

    async def test_throttles_rapid_requests_to_same_host(self):
        inner = FakeFetcher((("api.test", {}),))
        clock = _Clock()
        fetcher = CachingFetcher(
            inner,
            ttl_seconds=0.0,
            min_interval_seconds=1.0,
            time_fn=clock.time,
            sleep_fn=clock.sleep,
        )
        await fetcher.get_json("https://api.test/x", {"q": "a"})
        await fetcher.get_json("https://api.test/x", {"q": "b"})
        assert clock.sleeps == [1.0]

    async def test_serializes_concurrent_dispatch_to_a_host(self):
        # Two concurrent calls to one host must dispatch one at a time so the
        # throttle interval is honored; without the per-host lock the second
        # would enter the inner fetcher before the first returned.
        gate = asyncio.Event()
        order: list[str] = []

        class _BlockingFetcher(Fetcher):
            async def get_json(self, url, params):
                order.append(f"enter:{params['q']}")
                if params["q"] == "a":
                    await gate.wait()
                order.append(f"exit:{params['q']}")
                return {}

            async def post_json(self, url, payload):  # pragma: no cover - unused
                return {}

        fetcher = CachingFetcher(
            _BlockingFetcher(), ttl_seconds=0.0, min_interval_seconds=0.0, time_fn=_Clock().time
        )
        task_a = asyncio.create_task(fetcher.get_json("https://api.test/x", {"q": "a"}))
        task_b = asyncio.create_task(fetcher.get_json("https://api.test/x", {"q": "b"}))
        await asyncio.sleep(0)  # let a acquire the host lock and block on the gate
        await asyncio.sleep(0)  # let b queue behind the lock
        gate.set()
        await asyncio.gather(task_a, task_b)
        assert order == ["enter:a", "exit:a", "enter:b", "exit:b"]

    async def test_unregistered_fake_url_raises(self):
        with pytest.raises(ExternalFetchError):
            await FakeFetcher(()).get_json("https://api.test/x", {})


class TestHttpxFetcher:
    @staticmethod
    def _patch_transport(monkeypatch, handler) -> None:
        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

    async def test_parses_small_json_body(self, monkeypatch):
        self._patch_transport(monkeypatch, lambda request: httpx.Response(200, json={"ok": True}))
        fetcher = HttpxFetcher(max_response_bytes=1_000_000)
        assert await fetcher.get_json("https://api.test/x", {"q": "a"}) == {"ok": True}

    async def test_rejects_response_over_byte_cap(self, monkeypatch):
        self._patch_transport(monkeypatch, lambda request: httpx.Response(200, content=b"x" * 50))
        fetcher = HttpxFetcher(max_response_bytes=10)
        with pytest.raises(ExternalFetchError, match="cap"):
            await fetcher.get_json("https://api.test/x", {})

    async def test_status_error_is_translated_without_leaking_query(self, monkeypatch):
        self._patch_transport(monkeypatch, lambda request: httpx.Response(429))
        fetcher = HttpxFetcher()
        with pytest.raises(ExternalFetchError, match="status 429") as caught:
            await fetcher.get_json("https://api.test/x", {"api_key": "sk-secret"})
        assert "sk-secret" not in str(caught.value)
        assert caught.value.status_code == 429


class TestOpenFDATool:
    async def test_maude_maps_records_and_types_provenance(self):
        tool = OpenFDATool(offline_fetcher(), _settings())
        result = await tool.maude_events("infusion pump")
        assert result.provenance == "external"
        assert result.tool == "openfda_maude"
        assert [r["report_number"] for r in result.rows] == [
            "SYNTH-MAUDE-0001",
            "SYNTH-MAUDE-0002",
        ]
        assert result.rows[0]["brand_name"] == "SYNTH Infusion Pump 20"
        assert "telemetry dropout" in result.rows[0]["narrative"]
        text = result.to_text()
        assert text.startswith("EXTERNAL SOURCE (not QMS evidence):")
        assert "SYNTH-MAUDE-0001" in text

    async def test_each_endpoint_returns_rows(self):
        tool = OpenFDATool(offline_fetcher(), _settings())
        for method, argument in (
            (tool.recalls, "infusion pump"),
            (tool.clearances_510k, "infusion pump"),
            (tool.pma_approvals, "infusion pump"),
            (tool.gudid, "Synthetic Infusion Pump"),
            (tool.compliance_actions, "Synthetic Devices Inc"),
        ):
            result = await method(argument)
            assert result.provenance == "external"
            assert result.rows, result.tool
            assert result.query == argument

    async def test_maude_captures_meta_total_not_page_length(self):
        tool = OpenFDATool(offline_fetcher(), _settings())
        result = await tool.maude_events("infusion pump")
        # The offline page holds two rows, but meta.results.total is the true
        # match count and the only sound basis for a rate.
        assert len(result.rows) == 2
        assert result.total == 128
        assert "Total matching records reported by the source: 128" in result.to_text()

    async def test_missing_or_invalid_meta_total_is_none(self):
        for meta in ({"results": {"skip": 0}}, {"results": {"total": -1}}, {"results": "x"}):
            fetcher = FakeFetcher((("/device/event.json", {"meta": meta, "results": []}),))
            result = await OpenFDATool(fetcher, _settings()).maude_events("infusion pump")
            assert result.total is None
            assert "Total matching records" not in result.to_text()

    async def test_api_key_sent_as_param_but_never_in_audit_url(self):
        fetcher = offline_fetcher()
        tool = OpenFDATool(fetcher, _settings(openfda_api_key=SecretStr("sk-test-123")))
        result = await tool.maude_events("infusion pump")
        _method, _url, params = fetcher.requests[0]
        assert params["api_key"] == "sk-test-123"
        assert "sk-test-123" not in result.url
        assert "sk-test-123" not in result.to_text()

    async def test_malformed_payload_raises_typed_failure(self):
        fetcher = FakeFetcher((("/device/event.json", {"unexpected": "shape"}),))
        tool = OpenFDATool(fetcher, _settings())
        with pytest.raises(MalformedExternalResponseError, match="results"):
            await tool.maude_events("infusion pump")

    async def test_http_404_is_a_valid_empty_result(self):
        class NotFoundFetcher(FakeFetcher):
            def _lookup(self, method, url, body):
                raise ExternalFetchError(f"GET {url} returned status 404", status_code=404)

        tool = OpenFDATool(NotFoundFetcher(()), _settings())
        result = await tool.maude_events("device nobody has heard of")
        assert result.is_empty
        assert "(no matching records)" in result.to_text()

    async def test_other_http_errors_propagate(self):
        class RateLimitedFetcher(FakeFetcher):
            def _lookup(self, method, url, body):
                raise ExternalFetchError(f"GET {url} returned status 429", status_code=429)

        tool = OpenFDATool(RateLimitedFetcher(()), _settings())
        with pytest.raises(ExternalFetchError, match="429"):
            await tool.maude_events("infusion pump")


class TestECFRTool:
    async def test_regulation_search_maps_citation_and_strips_tags(self):
        tool = ECFRTool(offline_fetcher(), _settings())
        result = await tool.search_regulations("corrective and preventive action")
        assert result.provenance == "external"
        assert result.tool == "ecfr_search"
        assert result.rows[0]["citation"] == "21 CFR 820.100"
        assert result.rows[0]["heading"] == "Corrective and preventive action."
        assert result.to_text().startswith("EXTERNAL SOURCE (not QMS evidence):")

    async def test_guidance_filters_client_side_and_strips_html(self):
        tool = ECFRTool(offline_fetcher(), _settings())
        result = await tool.guidance_documents("cybersecurity")
        assert result.tool == "fda_guidance"
        assert len(result.rows) == 1
        assert result.rows[0]["title"] == "SYNTH Guidance: Cybersecurity in Medical Devices"
        assert result.rows[0]["docket"] == "SYNTH-D-0001"

    async def test_guidance_accepts_bare_list_payload(self):
        fetcher = FakeFetcher(
            (
                (
                    "search-for-guidance.json",
                    [{"title": "SYNTH bare-list guidance", "field_issue_datetime": "2025-01-01"}],
                ),
            )
        )
        result = await ECFRTool(fetcher, _settings()).guidance_documents("bare-list")
        assert result.rows[0]["title"] == "SYNTH bare-list guidance"

    async def test_malformed_payload_raises_typed_failure(self):
        fetcher = FakeFetcher((("ecfr.gov/api/search", {"unexpected": "shape"}),))
        with pytest.raises(MalformedExternalResponseError, match="results"):
            await ECFRTool(fetcher, _settings()).search_regulations("anything")

    async def test_malformed_guidance_index_raises_typed_failure(self):
        fetcher = FakeFetcher((("search-for-guidance.json", {"unexpected": "shape"}),))
        with pytest.raises(MalformedExternalResponseError, match="guidance"):
            await ECFRTool(fetcher, _settings()).guidance_documents("anything")


class TestClinicalTrialsTool:
    async def test_maps_protocol_section_fields(self):
        tool = ClinicalTrialsTool(offline_fetcher(), _settings())
        result = await tool.search("infusion pump")
        assert result.provenance == "external"
        assert result.tool == "clinicaltrials_search"
        assert result.rows[0]["nct_id"] == "SYNTH-NCT90000001"
        assert result.rows[0]["sponsor"] == "Synthetic Devices Inc"
        assert result.rows[0]["status"] == "COMPLETED"

    async def test_malformed_study_yields_blank_fields_not_crash(self):
        fetcher = FakeFetcher((("clinicaltrials.gov/api/v2/studies", {"studies": [{}]}),))
        result = await ClinicalTrialsTool(fetcher, _settings()).search("anything")
        assert result.rows[0]["nct_id"] == ""

    async def test_malformed_payload_raises_typed_failure(self):
        fetcher = FakeFetcher((("clinicaltrials.gov/api/v2/studies", {"unexpected": []}),))
        with pytest.raises(MalformedExternalResponseError, match="studies"):
            await ClinicalTrialsTool(fetcher, _settings()).search("anything")


class TestPubMedTool:
    async def test_two_step_search_joins_ids_to_summaries(self):
        fetcher = offline_fetcher()
        tool = PubMedTool(fetcher, _settings())
        result = await tool.search("intrathecal infusion outcomes")
        assert result.provenance == "external"
        assert result.tool == "pubmed_search"
        assert [r["pmid"] for r in result.rows] == ["90000001", "90000002"]
        assert result.rows[0]["first_author"] == "Synthson A"
        assert result.rows[1]["journal"] == "Synth Med Device Rev"
        methods_and_urls = [(m, u) for m, u, _ in fetcher.requests]
        assert "esearch.fcgi" in methods_and_urls[0][1]
        assert "esummary.fcgi" in methods_and_urls[1][1]

    async def test_empty_idlist_skips_esummary(self):
        fetcher = FakeFetcher((("esearch.fcgi", {"esearchresult": {"idlist": []}}),))
        result = await PubMedTool(fetcher, _settings()).search("no matches")
        assert result.is_empty
        assert len(fetcher.requests) == 1

    async def test_malformed_esearch_raises_typed_failure(self):
        fetcher = FakeFetcher((("esearch.fcgi", {"unexpected": "shape"}),))
        with pytest.raises(MalformedExternalResponseError, match="esearchresult"):
            await PubMedTool(fetcher, _settings()).search("anything")


class TestWebSearchTool:
    async def test_tavily_provider_maps_results(self):
        tool = WebSearchTool(
            TavilyWebSearchProvider(offline_fetcher(), "tvly-test-key"), _settings()
        )
        result = await tool.search("ISO 13485 audit checklist")
        assert result.provenance == "external"
        assert result.tool == "web_search"
        assert result.source == "Tavily web search"
        assert result.rows[0]["url"] == "https://example.invalid/synthetic-web-result"

    async def test_api_key_sent_in_payload_but_never_in_result(self):
        fetcher = offline_fetcher()
        tool = WebSearchTool(TavilyWebSearchProvider(fetcher, "tvly-secret-456"), _settings())
        result = await tool.search("anything")
        _method, _url, payload = fetcher.requests[0]
        assert payload["api_key"] == "tvly-secret-456"
        assert "tvly-secret-456" not in result.url
        assert "tvly-secret-456" not in result.to_text()

    async def test_build_web_search_without_key_uses_fake_provider(self):
        tool = build_web_search(offline_fetcher(), _settings(), None)
        assert isinstance(tool._provider, FakeWebSearchProvider)
        result = await tool.search("anything")
        assert result.source == "synthetic web search (offline)"
        assert "Synthetic" in result.rows[0]["title"]

    async def test_build_web_search_with_key_uses_tavily(self):
        tool = build_web_search(offline_fetcher(), _settings(), "tvly-key")
        assert isinstance(tool._provider, TavilyWebSearchProvider)


def test_safe_url_strips_query_string():
    url = "https://api.fda.gov/device/event.json?search=x&api_key=sk-sentinel-999"
    assert _safe_url(url) == "https://api.fda.gov/device/event.json"
    assert "sk-sentinel-999" not in _safe_url(url)


def test_build_fetcher_offline_uses_synthetic_payloads():
    fetcher = build_fetcher(_settings(offline=True))
    assert isinstance(fetcher, FakeFetcher)


def test_build_fetcher_live_is_caching():
    fetcher = build_fetcher(_settings(offline=False))
    assert isinstance(fetcher, CachingFetcher)
