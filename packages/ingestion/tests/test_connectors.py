"""Connector contract tests.

Every test parametrized over `make_connector` runs identically against the
filesystem connector and the SharePoint stub — the contract a real
Graph-backed SharePoint connector must also satisfy.
"""

import os
import shutil
from datetime import UTC, datetime

import pytest
from gg_ingestion.connectors import (
    ConnectorError,
    FilesystemConnector,
    SharePointStubConnector,
    SourceConnector,
    sync_connector,
)
from gg_ingestion.connectors.sync import default_manifest_path

_T1 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
_T2 = datetime(2026, 3, 2, 9, 30, tzinfo=UTC)

_SPEC = {
    "01_quality_manual/QM-100_Quality_Manual_revC.docx": (b"quality manual bytes", _T1),
    "05_capa/CAPA-2025-0001.docx": (b"capa record", _T1),
    "logs/readings.csv": (b"a,b\n1,2\n", _T2),
}


def _filesystem_factory(tmp_path):
    root = tmp_path / "source"

    def make(spec):
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        for source_id, (content, modified) in spec.items():
            path = root / source_id
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            os.utime(path, (modified.timestamp(), modified.timestamp()))
        return FilesystemConnector(root)

    return make


def _sharepoint_factory(tmp_path):
    def make(spec):
        return SharePointStubConnector(
            {source_id: (modified, content) for source_id, (content, modified) in spec.items()}
        )

    return make


@pytest.fixture(params=["filesystem", "sharepoint-stub"])
def make_connector(request, tmp_path):
    factory = _filesystem_factory if request.param == "filesystem" else _sharepoint_factory
    return factory(tmp_path)


async def test_listing_reports_every_document(make_connector):
    connector = make_connector(_SPEC)
    assert isinstance(connector, SourceConnector)
    documents = await connector.list_documents()
    assert [d.source_id for d in documents] == sorted(_SPEC)
    for document in documents:
        content, modified = _SPEC[document.source_id]
        assert document.size == len(content)
        assert document.modified == modified
        assert document.modified.tzinfo is not None
        assert document.name == document.source_id.rsplit("/", 1)[-1]


async def test_fetch_returns_listed_bytes(make_connector):
    connector = make_connector(_SPEC)
    for document in await connector.list_documents():
        assert await connector.fetch(document.source_id) == _SPEC[document.source_id][0]


async def test_fetch_unknown_id_raises(make_connector):
    connector = make_connector(_SPEC)
    with pytest.raises(ConnectorError):
        await connector.fetch("nope/missing.docx")


async def test_sync_materializes_then_reports_unchanged(make_connector, tmp_path):
    staging = tmp_path / "staging"
    connector = make_connector(_SPEC)
    first = await sync_connector(connector, staging)
    assert sorted(first.fetched) == sorted(_SPEC)
    assert first.unchanged == ()
    assert first.deleted == ()
    assert first.changed
    for source_id, (content, _) in _SPEC.items():
        assert (staging / source_id).read_bytes() == content
    second = await sync_connector(connector, staging)
    assert second.fetched == ()
    assert second.deleted == ()
    assert sorted(second.unchanged) == sorted(_SPEC)
    assert not second.changed


async def test_sync_detects_modification_and_deletion(make_connector, tmp_path):
    staging = tmp_path / "staging"
    await sync_connector(make_connector(_SPEC), staging)
    changed = dict(_SPEC)
    changed["05_capa/CAPA-2025-0001.docx"] = (b"capa record rev B", _T2)
    del changed["logs/readings.csv"]
    report = await sync_connector(make_connector(changed), staging)
    assert report.fetched == ("05_capa/CAPA-2025-0001.docx",)
    assert report.deleted == ("logs/readings.csv",)
    assert report.unchanged == ("01_quality_manual/QM-100_Quality_Manual_revC.docx",)
    assert (staging / "05_capa/CAPA-2025-0001.docx").read_bytes() == b"capa record rev B"
    assert not (staging / "logs/readings.csv").exists()


async def test_manifest_stays_outside_the_staging_corpus(make_connector, tmp_path):
    staging = tmp_path / "staging"
    await sync_connector(make_connector(_SPEC), staging)
    assert default_manifest_path(staging).is_file()
    staged = sorted(p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file())
    assert staged == sorted(_SPEC)


async def test_sync_rejects_source_ids_escaping_staging(tmp_path):
    connector = SharePointStubConnector({"../evil.docx": (_T1, b"payload")})
    with pytest.raises(ConnectorError):
        await sync_connector(connector, tmp_path / "staging")


async def test_filesystem_skips_hidden_files(tmp_path):
    root = tmp_path / "source"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_bytes(b"x")
    (root / ".DS_Store").write_bytes(b"x")
    (root / "SOP-001.docx").write_bytes(b"sop")
    documents = await FilesystemConnector(root).list_documents()
    assert [d.source_id for d in documents] == ["SOP-001.docx"]


async def test_filesystem_fetch_rejects_traversal(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (tmp_path / "secret.txt").write_bytes(b"secret")
    with pytest.raises(ConnectorError):
        await FilesystemConnector(root).fetch("../secret.txt")


def test_filesystem_requires_existing_root(tmp_path):
    with pytest.raises(ConnectorError):
        FilesystemConnector(tmp_path / "absent")
