"""SharePoint connector stub.

A real SharePoint connector authenticates against Microsoft Graph with
GG_SHAREPOINT_TENANT_ID / GG_SHAREPOINT_CLIENT_ID / GG_SHAREPOINT_CLIENT_SECRET
and lists a drive by site + library. No such credentials exist in this
environment, so this stub holds the drive in memory while honouring the full
SourceConnector contract — the contract tests exercise it alongside the
filesystem connector, so a real Graph-backed implementation can replace it
without touching the sync engine or pipeline.
"""

from collections.abc import Mapping
from datetime import datetime

from gg_ingestion.connectors.base import ConnectorError, SourceDocument


class SharePointStubConnector:
    name = "sharepoint-stub"

    def __init__(self, items: Mapping[str, tuple[datetime, bytes]]) -> None:
        """items maps a drive-relative path to (modified, content)."""
        self._items = dict(items)

    async def list_documents(self) -> tuple[SourceDocument, ...]:
        return tuple(
            SourceDocument(
                source_id=source_id,
                name=source_id.rsplit("/", 1)[-1],
                modified=modified,
                size=len(content),
            )
            for source_id, (modified, content) in sorted(self._items.items())
        )

    async def fetch(self, source_id: str) -> bytes:
        try:
            return self._items[source_id][1]
        except KeyError:
            raise ConnectorError(f"unknown source_id: {source_id}") from None
