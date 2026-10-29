"""Audit readiness report proof against live services: the full report must
reproduce every defect gg_synthdata seeds into the corpus. This is the
acceptance gate for the audit workflow — a deterministic sweep that surfaces
DEF-001 through DEF-005 without being told where to look."""

import pytest
from fastapi.testclient import TestClient
from goldengoose_api.main import create_app

pytestmark = pytest.mark.integration


def _mint(client, email):
    response = client.post("/auth/dev-token", json={"email": email, "role": "qa_user"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _result(report, check_id):
    matches = [r for r in report["results"] if r["check_id"] == check_id]
    assert matches, f"{check_id} missing from report"
    return matches[0]


def _finding_rows(report, check_id):
    result = _result(report, check_id)
    assert result["status"] == "finding", result
    return result["rows"]


def test_report_reproduces_every_seeded_defect(derived_corpus):
    with TestClient(create_app()) as client:
        auth = _mint(client, "auditor@example.com")
        response = client.get("/audit/report", headers=auth)
        assert response.status_code == 200
        report = response.json()

        assert not [r for r in report["results"] if r["status"] == "error"], report

        # DEF-001 broken_trace_link: REQ-017 has no verification in TM-100.
        rows = _finding_rows(report, "unverified_requirements")
        assert any(row["req_id"] == "REQ-017" for row in rows), rows

        # DEF-002 ap_mismatch: DFMEA-100 row 3 records M where the table says H.
        rows = _finding_rows(report, "fmea_ap_mismatches")
        mismatch = [r for r in rows if r["doc_key"] == "DFMEA-100" and r["row_id"] == 3]
        assert mismatch, rows
        assert mismatch[0]["ap_recorded"] != mismatch[0]["ap_computed"]

        # DEF-003 overdue_effectiveness_check: CAPA-2025-007 past its due date.
        rows = _finding_rows(report, "overdue_capa_effectiveness")
        assert any(row["capa_id"] == "CAPA-2025-007" for row in rows), rows

        # DEF-004 complaint_without_risk_evaluation: C-2025-0142 has none.
        rows = _finding_rows(report, "complaints_without_risk_evaluation")
        assert any(row["complaint_id"] == "C-2025-0142" for row in rows), rows

        # DEF-005 stale_sop_reference: SOP-016 cites WI-101 Rev A; WI-101 moved on.
        rows = _finding_rows(report, "stale_document_references")
        stale = [r for r in rows if r["doc_key"] == "SOP-016" and r["referenced_doc"] == "WI-101"]
        assert stale, rows
        assert stale[0]["cited_revision"] == "A"
        assert stale[0]["current_revision"] != "A"

        # The summary counts findings and the advisory always says something.
        assert "with findings" in report["summary"]
        assert report["advisory"].strip()


def test_collections_filter_and_unknown_collection(derived_corpus):
    with TestClient(create_app()) as client:
        auth = _mint(client, "auditor@example.com")

        listed = client.get("/audit/collections", headers=auth)
        assert listed.status_code == 200
        collections = {c["collection_id"]: c for c in listed.json()}
        assert "design_controls" in collections
        assert collections["design_controls"]["checks"]

        scoped = client.get("/audit/report?collection=design_controls", headers=auth)
        assert scoped.status_code == 200
        scoped_report = scoped.json()
        assert scoped_report["collection_id"] == "design_controls"
        assert {r["check_id"] for r in scoped_report["results"]} == {
            c["check_id"] for c in collections["design_controls"]["checks"]
        }

        missing = client.get("/audit/report?collection=nonexistent", headers=auth)
        assert missing.status_code == 404

        anonymous = client.get("/audit/report")
        assert anonymous.status_code == 401
