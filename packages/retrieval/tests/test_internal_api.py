"""Internal-API connector framework tests: config parsing and validation,
credential scoping (fail-fast, never echoed), the resource whitelist, role
gating for restricted connectors, and response-to-rows normalization."""

import json

import pytest
from gg_common.settings import InternalApiSettings
from gg_retrieval.tools.internal_api import (
    FakeInternalApiClient,
    InternalApiError,
    build_internal_api_registry,
    parse_connectors,
)

EQMS = {
    "name": "eqms",
    "title": "eQMS",
    "base_url": "https://eqms.internal/",
    "resources": {"open_changes": "/api/v1/changes", "audit_findings": "/api/v1/findings"},
    "api_key_env": "EQMS_API_KEY",
    "restricted": False,
}

ERP_RESTRICTED = {
    "name": "erp",
    "title": "ERP complaints feed",
    "base_url": "http://erp.internal",
    "resources": {"complaints": "/complaints"},
    "restricted": True,
}


def settings_for(*connectors: dict) -> InternalApiSettings:
    return InternalApiSettings(connectors_json=json.dumps(list(connectors)), result_limit=3)


def make_registry(*connectors: dict, responses=(), env=None):
    client = FakeInternalApiClient(responses)
    resolved_env = {"EQMS_API_KEY": "sekret-token"} if env is None else env
    registry = build_internal_api_registry(
        settings_for(*connectors), client=client, env=resolved_env
    )
    return registry, client


class TestConfig:
    def test_valid_declarations_parse(self):
        connectors = parse_connectors(settings_for(EQMS, ERP_RESTRICTED))
        assert [c.name for c in connectors] == ["eqms", "erp"]
        assert connectors[0].base_url == "https://eqms.internal"  # trailing slash stripped
        assert connectors[1].restricted

    def test_invalid_json_rejected(self):
        with pytest.raises(InternalApiError, match="not valid JSON"):
            parse_connectors(InternalApiSettings(connectors_json="{nope"))

    def test_non_array_rejected(self):
        with pytest.raises(InternalApiError, match="JSON array"):
            parse_connectors(InternalApiSettings(connectors_json='{"name": "x"}'))

    def test_duplicate_names_rejected(self):
        with pytest.raises(InternalApiError, match="duplicate connector names: eqms"):
            parse_connectors(settings_for(EQMS, EQMS))

    def test_unrooted_resource_path_rejected(self):
        bad = {**EQMS, "resources": {"changes": "api/v1/changes"}}
        with pytest.raises(ValueError, match="must start with"):
            parse_connectors(settings_for(bad))

    def test_non_http_base_url_rejected(self):
        bad = {**EQMS, "base_url": "ftp://eqms.internal"}
        with pytest.raises(ValueError, match="http"):
            parse_connectors(settings_for(bad))

    def test_unknown_fields_rejected(self):
        bad = {**EQMS, "allow_post": True}
        with pytest.raises(ValueError, match="allow_post"):
            parse_connectors(settings_for(bad))

    def test_missing_access_classification_rejected(self):
        unclassified = {k: v for k, v in EQMS.items() if k != "restricted"}
        with pytest.raises(ValueError, match="restricted"):
            parse_connectors(settings_for(unclassified))


class TestCredentials:
    def test_missing_credential_fails_at_build(self):
        with pytest.raises(InternalApiError) as excinfo:
            make_registry(EQMS, env={})
        assert "EQMS_API_KEY" in str(excinfo.value)

    async def test_credential_scoped_to_its_connector(self):
        registry, client = make_registry(
            EQMS, ERP_RESTRICTED, responses=(("changes", []), ("complaints", []))
        )
        await registry.call("eqms", "open_changes", role="qa_user")
        await registry.call("erp", "complaints", role="qa_user")
        eqms_headers = client.requests[0][2]
        erp_headers = client.requests[1][2]
        assert eqms_headers == {"Authorization": "Bearer sekret-token"}
        assert erp_headers == {}  # keyless connector sends no credential

    def test_discovery_never_exposes_credentials(self):
        registry, _ = make_registry(EQMS)
        listed = json.dumps(registry.connectors())
        assert "sekret-token" not in listed
        assert "EQMS_API_KEY" not in listed


class TestCall:
    async def test_unknown_connector_lists_available(self):
        registry, _ = make_registry(EQMS)
        with pytest.raises(LookupError, match="available: eqms"):
            await registry.call("mrp", "open_changes", role="qa_user")

    async def test_unknown_resource_lists_available(self):
        registry, client = make_registry(EQMS)
        with pytest.raises(LookupError, match="audit_findings, open_changes"):
            await registry.call("eqms", "closed_changes", role="qa_user")
        assert client.requests == []

    async def test_restricted_connector_refuses_auditor_before_any_request(self):
        registry, client = make_registry(ERP_RESTRICTED, env={})
        with pytest.raises(InternalApiError, match="qa_user or admin"):
            await registry.call("erp", "complaints", role="auditor_readonly")
        assert client.requests == []

    async def test_restricted_connector_allows_qa_user(self):
        registry, _ = make_registry(
            ERP_RESTRICTED, responses=(("complaints", [{"id": "C-1"}]),), env={}
        )
        result = await registry.call("erp", "complaints", role="qa_user")
        assert result.rows == ({"id": "C-1"},)

    async def test_rows_capped_and_truncated(self):
        payload = [{"id": i} for i in range(5)]
        registry, _ = make_registry(EQMS, responses=(("changes", payload),))
        result = await registry.call("eqms", "open_changes", role="qa_user")
        assert len(result.rows) == 3  # settings_for sets result_limit=3
        assert result.truncated

    async def test_object_payload_becomes_one_row(self):
        registry, _ = make_registry(EQMS, responses=(("changes", {"open": 4, "closed": 9}),))
        result = await registry.call("eqms", "open_changes", role="qa_user")
        assert result.rows == ({"open": 4, "closed": 9},)
        assert result.columns == ("open", "closed")

    async def test_scalar_payload_is_wrapped(self):
        registry, _ = make_registry(EQMS, responses=(("changes", 12),))
        result = await registry.call("eqms", "open_changes", role="qa_user")
        assert result.rows == ({"value": 12},)

    async def test_result_shape_for_citation(self):
        registry, _ = make_registry(EQMS, responses=(("changes", []),))
        result = await registry.call("eqms", "open_changes", {"status": "open"}, role="qa_user")
        assert result.tool == "internal_api"
        assert result.title == "eQMS: open_changes"
        assert result.source == "eQMS (https://eqms.internal)"
        assert result.query == 'GET /api/v1/changes {"status": "open"}'

    async def test_transport_error_propagates_without_credential(self):
        registry, _ = make_registry(EQMS)  # no fake response registered
        with pytest.raises(InternalApiError) as excinfo:
            await registry.call("eqms", "open_changes", role="qa_user")
        assert "sekret-token" not in str(excinfo.value)
