"""Internal-API connector framework: read-only, config-registered,
credential-scoped access to the company's own business systems (eQMS, ERP,
LIMS) at answer time.

Connectors are declared in configuration (GG_INTERNAL_CONNECTORS_JSON), never
in code: each names its base URL, an explicit whitelist of GET resources, and
the environment variable holding its credential. Credentials are scoped to
their connector — resolved once at registry build (missing ones fail fast),
attached only to that connector's requests, and never echoed in errors. The
client seam has no verb but GET, so the framework is read-only by
construction. Every declaration must state its access classification
(restricted true/false) explicitly, and every call must name the caller's
role — a restricted connector refuses roles without restricted access, the
same rule every other tool path takes from gg_common.acl.
"""

import json
import os
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from typing import Any

import httpx
from gg_common import acl
from gg_common.settings import InternalApiSettings
from pydantic import BaseModel, ConfigDict, field_validator

from gg_retrieval.tools.http_limits import DEFAULT_MAX_RESPONSE_BYTES, read_capped_bytes
from gg_retrieval.tools.models import ToolResult, plain_row


class InternalApiError(Exception):
    """Configuration, authorization, or transport failure for a connector."""


class ConnectorConfig(BaseModel):
    """One declared connector. resources maps a short name the agent can cite
    to the exact GET path it is allowed to reach — nothing off this whitelist
    is requestable."""

    model_config = ConfigDict(extra="forbid")

    name: str
    title: str
    base_url: str
    resources: dict[str, str]
    api_key_env: str | None = None
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer "
    # No default: whoever declares a connector must decide whether its data
    # is restricted. An unclassified connector is a config error, not general.
    restricted: bool

    @field_validator("name", "title")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("base_url")
    @classmethod
    def _http_base(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        return value.rstrip("/")

    @field_validator("resources")
    @classmethod
    def _rooted_paths(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("a connector must declare at least one resource")
        for resource, path in value.items():
            if not resource.strip():
                raise ValueError("resource names must not be empty")
            if not path.startswith("/"):
                raise ValueError(f"resource '{resource}' path must start with '/'")
        return value


def parse_connectors(settings: InternalApiSettings) -> tuple[ConnectorConfig, ...]:
    try:
        raw = json.loads(settings.connectors_json)
    except json.JSONDecodeError as exc:
        raise InternalApiError(f"GG_INTERNAL_CONNECTORS_JSON is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise InternalApiError("GG_INTERNAL_CONNECTORS_JSON must be a JSON array")
    connectors = tuple(ConnectorConfig.model_validate(item) for item in raw)
    names = [c.name for c in connectors]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise InternalApiError(f"duplicate connector names: {', '.join(duplicates)}")
    return connectors


class InternalApiClient(ABC):
    """Transport seam. GET is the only verb on purpose."""

    @abstractmethod
    async def get_json(self, url: str, params: dict[str, Any], headers: dict[str, str]) -> Any: ...


class HttpxInternalApiClient(InternalApiClient):
    def __init__(
        self,
        timeout_seconds: float = 10.0,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_bytes = max_response_bytes

    async def get_json(self, url: str, params: dict[str, Any], headers: dict[str, str]) -> Any:
        # Error messages name only the whitelisted URL (base + path, no query
        # string) and the failure class — never str(exc), which httpx builds
        # from the full request URL including params. The body is streamed under
        # a byte cap so an oversized response cannot exhaust worker memory.
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream("GET", url, params=params, headers=headers) as response,
            ):
                response.raise_for_status()
                body = await read_capped_bytes(
                    response,
                    max_bytes=self._max_bytes,
                    target=f"GET {url}",
                    on_exceeded=InternalApiError,
                )
            return json.loads(body)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise InternalApiError(f"GET {url} returned status {status}") from exc
        except httpx.HTTPError as exc:
            raise InternalApiError(f"GET {url} failed: {type(exc).__name__}") from exc


class FakeInternalApiClient(InternalApiClient):
    """Canned responses keyed by URL substring; records every request."""

    def __init__(self, responses: tuple[tuple[str, Any], ...] = ()) -> None:
        self._responses = responses
        self.requests: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def get_json(self, url: str, params: dict[str, Any], headers: dict[str, str]) -> Any:
        self.requests.append((url, params, headers))
        for fragment, payload in self._responses:
            if fragment in url:
                return payload
        raise InternalApiError(f"no fake response registered for {url}")


class InternalApiRegistry:
    def __init__(
        self,
        *,
        settings: InternalApiSettings,
        client: InternalApiClient,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self._connectors = {c.name: c for c in parse_connectors(settings)}
        self._credentials = _resolve_credentials(
            self._connectors.values(), os.environ if env is None else env
        )

    def connectors(self) -> tuple[dict[str, Any], ...]:
        """Declared connectors for discovery — everything but credentials."""
        return tuple(
            {
                "name": c.name,
                "title": c.title,
                "resources": sorted(c.resources),
                "restricted": c.restricted,
            }
            for c in self._connectors.values()
        )

    async def call(
        self,
        connector: str,
        resource: str,
        params: dict[str, Any] | None = None,
        *,
        role: str,
    ) -> ToolResult:
        config = self._connectors.get(connector)
        if config is None:
            available = ", ".join(sorted(self._connectors)) or "none configured"
            raise LookupError(f"unknown connector: {connector} (available: {available})")
        if config.restricted and not acl.can_read_restricted(role):
            raise InternalApiError(
                f"connector '{connector}' serves restricted records and requires"
                " the qa_user or admin role"
            )
        path = config.resources.get(resource)
        if path is None:
            available = ", ".join(sorted(config.resources))
            raise LookupError(
                f"unknown resource '{resource}' on connector '{connector}' (available: {available})"
            )

        url = config.base_url + path
        headers = {}
        credential = self._credentials.get(connector)
        if credential is not None:
            headers[config.api_key_header] = f"{config.api_key_prefix}{credential}"
        payload = await self.client.get_json(url, params or {}, headers)

        fetched = [plain_row(row) for row in _payload_rows(payload)]
        limit = self.settings.result_limit
        rows = tuple(fetched[:limit])
        columns = _columns(rows)
        query = f"GET {path}" + (f" {json.dumps(params, sort_keys=True)}" if params else "")
        return ToolResult(
            tool="internal_api",
            title=f"{config.title}: {resource}",
            source=f"{config.title} ({config.base_url})",
            query=query,
            columns=columns,
            rows=rows,
            truncated=len(fetched) > limit,
        )


def build_internal_api_registry(
    settings: InternalApiSettings,
    *,
    client: InternalApiClient | None = None,
    env: Mapping[str, str] | None = None,
) -> InternalApiRegistry:
    return InternalApiRegistry(
        settings=settings,
        client=client
        or HttpxInternalApiClient(
            timeout_seconds=settings.timeout_seconds,
            max_response_bytes=settings.max_response_bytes,
        ),
        env=env,
    )


def _resolve_credentials(
    connectors: Iterable[ConnectorConfig], env: Mapping[str, str]
) -> dict[str, str]:
    """Fail fast at build time: a declared credential env var must exist. The
    error names the variable, never a value."""
    credentials: dict[str, str] = {}
    for config in connectors:
        if config.api_key_env is None:
            continue
        value = env.get(config.api_key_env)
        if not value:
            raise InternalApiError(
                f"connector '{config.name}' requires credential env var"
                f" {config.api_key_env}, which is unset"
            )
        credentials[config.name] = value
    return credentials


def _payload_rows(payload: Any) -> list[dict[str, Any]]:
    """Normalize a JSON response to rows. Lists of objects pass through; a
    lone object is one row; anything else is wrapped so the evidence still
    renders and cites."""
    if isinstance(payload, list):
        return [row if isinstance(row, dict) else {"value": row} for row in payload]
    if isinstance(payload, dict):
        return [payload]
    return [{"value": payload}]


def _columns(rows: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return tuple(columns)
