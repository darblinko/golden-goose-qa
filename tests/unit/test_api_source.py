"""Source viewer route: ACL choke point plus registry-hash verification.

The route is exercised without a live database or object store: the version
lookup is monkeypatched to canned rows and the object store is a local
filesystem stub, so the test isolates the two guarantees the route adds — a
restricted family is never served to an auditor, and bytes that do not match
the registry hash fail closed."""

import hashlib

import pytest
from fastapi.testclient import TestClient
from gg_common.objectstore import LocalObjectStore
from gg_ingestion.registry import SourceVersion
from goldengoose_api.auth import mint_dev_token
from goldengoose_api.main import create_app
from goldengoose_api.routers import source_routes

BUCKET = "gg-documents"


class _NullSession:
    """Stand-in for the async session context manager; the version lookup is
    monkeypatched, so the session itself is never touched."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _source(*, doc_type, object_key, content_hash, doc_key="SOP-004", file_format="pdf"):
    return SourceVersion(
        version_id="v1",
        doc_key=doc_key,
        doc_type=doc_type,
        title="Title",
        revision="A",
        file_format=file_format,
        content_hash=content_hash,
        object_key=object_key,
    )


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    app = create_app()
    settings = app.state.settings
    store = LocalObjectStore(tmp_path)
    app.state.object_store = store
    app.state.session_factory = lambda: _NullSession()

    sources: dict[str, SourceVersion | None] = {}
    requested_versions: list[str | None] = []

    async def fake_fetch(session, *, doc_key, version_id=None):
        requested_versions.append(version_id)
        return sources.get(doc_key)

    monkeypatch.setattr(source_routes, "fetch_source_version", fake_fetch)

    def auth(role):
        token = mint_dev_token(settings, email=f"{role}@example.com", role=role)
        return {"Authorization": f"Bearer {token}"}

    return TestClient(app), store, sources, auth, requested_versions


def _store_doc(store, object_key, data):
    store.put(BUCKET, object_key, data)
    return hashlib.sha256(data).hexdigest()


def test_general_document_served_to_auditor(harness):
    client, store, sources, auth, _versions = harness
    data = b"%PDF-1.7 corrective and preventive action procedure"
    digest = _store_doc(store, "SOP-004/hash/sop.pdf", data)
    sources["SOP-004"] = _source(
        doc_type="sop", object_key="SOP-004/hash/sop.pdf", content_hash=digest
    )

    response = client.get("/sources/SOP-004", headers=auth("auditor_readonly"))
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"].startswith("application/pdf")


def test_restricted_document_denied_to_auditor(harness):
    client, store, sources, auth, _versions = harness
    data = b"complaint narrative"
    digest = _store_doc(store, "C-2025-0142/hash/complaint.pdf", data)
    sources["C-2025-0142"] = _source(
        doc_type="complaint",
        doc_key="C-2025-0142",
        object_key="C-2025-0142/hash/complaint.pdf",
        content_hash=digest,
    )

    denied = client.get("/sources/C-2025-0142", headers=auth("auditor_readonly"))
    assert denied.status_code == 403
    # The privileged control proves the record exists and only the role stands
    # between the auditor and its content.
    allowed = client.get("/sources/C-2025-0142", headers=auth("qa_user"))
    assert allowed.status_code == 200
    assert allowed.content == data


def test_unknown_doc_type_fails_closed_to_restricted(harness):
    client, store, sources, auth, _versions = harness
    data = b"unclassified family"
    digest = _store_doc(store, "X-1/hash/x.pdf", data)
    sources["X-1"] = _source(
        doc_type="not_a_known_type",
        doc_key="X-1",
        object_key="X-1/hash/x.pdf",
        content_hash=digest,
    )

    assert client.get("/sources/X-1", headers=auth("auditor_readonly")).status_code == 403
    assert client.get("/sources/X-1", headers=auth("qa_user")).status_code == 200


def test_hash_mismatch_fails_closed(harness):
    client, store, sources, auth, _versions = harness
    store.put(BUCKET, "SOP-004/hash/sop.pdf", b"the bytes actually on disk")
    sources["SOP-004"] = _source(
        doc_type="sop",
        object_key="SOP-004/hash/sop.pdf",
        content_hash="0" * 64,  # not the hash of the stored bytes
    )

    response = client.get("/sources/SOP-004", headers=auth("qa_user"))
    assert response.status_code == 500
    assert "integrity" in response.json()["detail"]


def test_unknown_document_returns_404(harness):
    client, _store, _sources, auth, _versions = harness
    assert client.get("/sources/NOPE-1", headers=auth("qa_user")).status_code == 404


def test_missing_token_is_unauthorized(harness):
    client, _store, _sources, _auth, _versions = harness
    assert client.get("/sources/SOP-004").status_code == 401


def test_version_query_param_pins_the_requested_revision(harness):
    client, store, sources, auth, versions = harness
    data = b"%PDF-1.7 superseded revision bytes"
    digest = _store_doc(store, "SOP-004/oldhash/sop.pdf", data)
    sources["SOP-004"] = _source(
        doc_type="sop", object_key="SOP-004/oldhash/sop.pdf", content_hash=digest
    )

    # A citation to an obsolete revision carries its version id; the route must
    # thread it to the resolver so the pinned revision is served, not the current.
    ok = client.get("/sources/SOP-004?version=ver-old", headers=auth("qa_user"))
    assert ok.status_code == 200
    assert versions == ["ver-old"]


def test_no_version_query_param_resolves_current(harness):
    client, store, sources, auth, versions = harness
    data = b"%PDF-1.7 current"
    digest = _store_doc(store, "SOP-004/hash/sop.pdf", data)
    sources["SOP-004"] = _source(
        doc_type="sop", object_key="SOP-004/hash/sop.pdf", content_hash=digest
    )

    client.get("/sources/SOP-004", headers=auth("qa_user"))
    assert versions == [None]
