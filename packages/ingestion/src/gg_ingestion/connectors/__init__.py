"""Source connectors: enumerate and fetch documents from external systems."""

from gg_ingestion.connectors.base import ConnectorError, SourceConnector, SourceDocument
from gg_ingestion.connectors.filesystem import FilesystemConnector
from gg_ingestion.connectors.sharepoint import SharePointStubConnector
from gg_ingestion.connectors.sync import SyncReport, acknowledge_sync, sync_connector

__all__ = [
    "ConnectorError",
    "FilesystemConnector",
    "SharePointStubConnector",
    "SourceConnector",
    "SourceDocument",
    "SyncReport",
    "acknowledge_sync",
    "sync_connector",
]
