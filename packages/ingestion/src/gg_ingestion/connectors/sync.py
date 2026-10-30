"""Sync engine: materialize a connector's documents into a staging corpus.

The staging directory is a plain local corpus the existing pipeline ingests
unchanged. Change detection compares each listing against a manifest kept
*beside* the staging directory (never inside it — the pipeline treats every
file in a corpus as a document and unrecognized files are hard failures).
The manifest records (modified, size) per source_id; a mismatch refetches,
a missing listing entry deletes the staged file.

With acknowledge=False the manifest is not advanced for fetched or deleted
documents; the caller calls acknowledge_sync for the changes its downstream
processing completed. Unacknowledged changes are reported again by the next
sync, so a failed ingestion or retirement is retried instead of forgotten.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from gg_ingestion.connectors.base import ConnectorError, SourceConnector


@dataclass(frozen=True)
class SyncReport:
    fetched: tuple[str, ...]
    unchanged: tuple[str, ...]
    deleted: tuple[str, ...]
    manifest_path: Path | None = None
    listed_entries: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

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
    acknowledge: bool = True,
) -> SyncReport:
    manifest_path = manifest_path or default_manifest_path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(manifest_path)

    fetched: list[str] = []
    unchanged: list[str] = []
    next_manifest: dict[str, dict[str, object]] = {}
    listed = await connector.list_documents()
    entries = _listed(listed)
    for document in listed:
        entry = entries[document.source_id]
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

    if not acknowledge:
        next_manifest = _withhold_changes(manifest, next_manifest, fetched, deleted)
    _save_manifest(manifest_path, next_manifest)
    return SyncReport(
        fetched=tuple(fetched),
        unchanged=tuple(unchanged),
        deleted=tuple(deleted),
        manifest_path=manifest_path,
        listed_entries=entries,
    )


def acknowledge_sync(report: SyncReport, *, fetched: Iterable[str], deleted: Iterable[str]) -> None:
    """Record fetched documents and deletions whose downstream processing succeeded."""
    if report.manifest_path is None:
        raise ConnectorError("sync report carries no manifest path to acknowledge")
    manifest = _load_manifest(report.manifest_path)
    for source_id in fetched:
        if source_id not in report.fetched:
            raise ConnectorError(f"cannot acknowledge {source_id}: not fetched by this sync")
        manifest[source_id] = dict(report.listed_entries[source_id])
    for source_id in deleted:
        if source_id not in report.deleted:
            raise ConnectorError(f"cannot acknowledge {source_id}: not deleted by this sync")
        manifest.pop(source_id, None)
    _save_manifest(report.manifest_path, manifest)


def _listed(listed) -> dict[str, dict[str, object]]:
    return {
        document.source_id: {"modified": document.modified.isoformat(), "size": document.size}
        for document in listed
    }


def _withhold_changes(
    previous: Mapping[str, dict[str, object]],
    proposed: Mapping[str, dict[str, object]],
    fetched: Iterable[str],
    deleted: Iterable[str],
) -> dict[str, dict[str, object]]:
    """The proposed manifest with fetched and deleted documents kept at their
    previous state, so the next sync reports them again."""
    withheld = dict(proposed)
    for source_id in fetched:
        if source_id in previous:
            withheld[source_id] = previous[source_id]
        else:
            withheld.pop(source_id, None)
    for source_id in deleted:
        withheld[source_id] = previous[source_id]
    return withheld


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
