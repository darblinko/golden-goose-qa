"""The SourceConnector contract.

A connector is the boundary between an external document source (file share,
SharePoint drive) and the ingestion pipeline. Connectors only enumerate and
fetch bytes — parsing, hashing, and idempotency stay in the pipeline, so
every source gets identical registration, gating, and audit treatment. The
contract tests in test_connectors.py run against every implementation.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


class ConnectorError(Exception):
    """A source could not be listed or a document could not be fetched."""


@dataclass(frozen=True)
class SourceDocument:
    """One document as reported by a source listing.

    source_id is stable within the source (a relative path for filesystem
    sources, a drive item path for SharePoint) and doubles as the relative
    location the sync engine materializes the file at.
    """

    source_id: str
    name: str
    modified: datetime  # timezone-aware, UTC
    size: int


@runtime_checkable
class SourceConnector(Protocol):
    name: str

    async def list_documents(self) -> tuple[SourceDocument, ...]:
        """All documents currently in the source, sorted by source_id."""
        ...

    async def fetch(self, source_id: str) -> bytes:
        """The document's bytes; raises ConnectorError for unknown ids."""
        ...
