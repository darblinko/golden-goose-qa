"""Filesystem connector: a directory tree as a document source.

Backs the watch-folder workflow — documents dropped into the root appear in
the next listing; the sync engine materializes them into the staging corpus.
Hidden files and directories (dotfiles, editor droppings) are excluded.
"""

from datetime import UTC, datetime
from pathlib import Path

from gg_ingestion.connectors.base import ConnectorError, SourceDocument


class FilesystemConnector:
    name = "filesystem"

    def __init__(self, root: Path) -> None:
        if not root.is_dir():
            raise ConnectorError(f"source root is not a directory: {root}")
        self.root = root.resolve()

    async def list_documents(self) -> tuple[SourceDocument, ...]:
        documents = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            stat = path.stat()
            documents.append(
                SourceDocument(
                    source_id=relative.as_posix(),
                    name=path.name,
                    modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    size=stat.st_size,
                )
            )
        return tuple(documents)

    async def fetch(self, source_id: str) -> bytes:
        path = self._resolve(source_id)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ConnectorError(f"cannot read {source_id}: {exc}") from exc

    def _resolve(self, source_id: str) -> Path:
        candidate = (self.root / source_id).resolve()
        if not candidate.is_relative_to(self.root):
            raise ConnectorError(f"source_id escapes the source root: {source_id}")
        if not candidate.is_file():
            raise ConnectorError(f"unknown source_id: {source_id}")
        return candidate
