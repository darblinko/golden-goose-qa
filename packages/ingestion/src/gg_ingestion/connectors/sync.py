"""Sync engine: materialize a connector's documents into a staging corpus.

The staging directory is a plain local corpus the existing pipeline ingests
unchanged. Change detection compares each listing against a manifest kept
*beside* the staging directory (never inside it — the pipeline treats every
file in a corpus as a document and unrecognized files are hard failures).
The manifest records (modified, size) per source_id; a mismatch refetches,
a missing listing entry deletes the staged file.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from gg_ingestion.connectors.base import ConnectorError, SourceConnector


@dataclass(frozen=True)
class SyncReport:
    fetched: tuple[str, ...]
    unchanged: tuple[str, ...]
    deleted: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.fetched or self.deleted)


def default_manifest_path(staging_dir: Path) -> Path:
    return staging_dir.parent / f"{staging_dir.name}.sync-manifest.json"


async def sync_connector(
    connector: SourceConnector,
    staging_dir: Path,
    *,
    manifest_path: Path | None = None,
) -> SyncReport:
    manifest_path = manifest_path or default_manifest_path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(manifest_path)

    fetched: list[str] = []
    unchanged: list[str] = []
    next_manifest: dict[str, dict[str, object]] = {}
    listed = await connector.list_documents()
    for document in listed:
        entry = {"modified": document.modified.isoformat(), "size": document.size}
        next_manifest[document.source_id] = entry
        if manifest.get(document.source_id) == entry:
            unchanged.append(document.source_id)
            continue
        content = await connector.fetch(document.source_id)
        target = _staging_path(staging_dir, document.source_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        fetched.append(document.source_id)

    deleted: list[str] = []
    for source_id in sorted(set(manifest) - {d.source_id for d in listed}):
        _staging_path(staging_dir, source_id).unlink(missing_ok=True)
        deleted.append(source_id)

    _save_manifest(manifest_path, next_manifest)
    return SyncReport(fetched=tuple(fetched), unchanged=tuple(unchanged), deleted=tuple(deleted))


def _staging_path(staging_dir: Path, source_id: str) -> Path:
    candidate = (staging_dir / source_id).resolve()
    if not candidate.is_relative_to(staging_dir.resolve()):
        raise ConnectorError(f"source_id escapes the staging directory: {source_id}")
    return candidate


def _load_manifest(manifest_path: Path) -> dict[str, dict[str, object]]:
    if not manifest_path.is_file():
        return {}
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConnectorError(f"corrupt sync manifest {manifest_path}: {exc}") from exc
    documents = raw.get("documents", {})
    if not isinstance(documents, dict):
        raise ConnectorError(f"corrupt sync manifest {manifest_path}: 'documents' is not a map")
    return documents


def _save_manifest(manifest_path: Path, documents: dict[str, dict[str, object]]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"synced_at": datetime.now(tz=UTC).isoformat(), "documents": documents}
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
