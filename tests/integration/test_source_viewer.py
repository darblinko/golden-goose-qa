"""Phase-8 evidence integrity: the source viewer serves a cited original only
after the ACL choke point and a registry-hash check. Runs against the ingested
corpus so the object store and registry are populated by real ingestion — a
200 therefore proves the stored bytes matched the recorded content hash."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from gg_common.acl import ACCESS_GENERAL, access_level_for
from gg_common.settings import get_settings
from goldengoose_api.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

RESTRICTED_DOC_KEY = "C-2025-0142"


def _mint(client, email, role):
    response = client.post("/auth/dev-token", json={"email": email, "role": role})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _a_general_doc_key() -> str | None:
    async def probe():
        settings = get_settings()
        engine = create_async_engine(settings.postgres.sqlalchemy_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT d.doc_key, d.doc_type FROM app.documents d "
                            "JOIN app.document_versions v ON v.document_id = d.id "
                            "WHERE v.pipeline_state = 'indexed' ORDER BY d.doc_key"
                        )
                    )
                ).all()
            for row in rows:
                if access_level_for(row.doc_type) == ACCESS_GENERAL:
                    return row.doc_key
            return None
        finally:
            await engine.dispose()

    return asyncio.run(probe())


def test_source_viewer_enforces_acl_and_integrity(ingested_corpus):
    general_key = _a_general_doc_key()
    assert general_key, "no indexed general document in corpus — control is broken"

    with TestClient(create_app()) as client:
        auditor = _mint(client, "external.auditor@example.com", "auditor_readonly")
        qa = _mint(client, "qa@example.com", "qa_user")

        # A general document is served to any authenticated role and passes the
        # registry-hash check (200 means read_verified did not raise).
        served = client.get(f"/sources/{general_key}", headers=auditor)
        assert served.status_code == 200, served.text
        assert served.content

        # The restricted complaint is denied to the auditor, served to QA —
        # the privileged control proves only the role stands between the
        # auditor and the record content.
        denied = client.get(f"/sources/{RESTRICTED_DOC_KEY}", headers=auditor)
        assert denied.status_code == 403
        privileged = client.get(f"/sources/{RESTRICTED_DOC_KEY}", headers=qa)
        assert privileged.status_code == 200, privileged.text
        assert privileged.content

        # Unknown documents 404; missing auth 401.
        assert client.get("/sources/DOES-NOT-EXIST", headers=qa).status_code == 404
        assert client.get(f"/sources/{general_key}").status_code == 401
