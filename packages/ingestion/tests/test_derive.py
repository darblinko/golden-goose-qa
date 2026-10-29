from datetime import date

from gg_ingestion.extract.derive import RegistryDocument, document_node, parsed_from_artifact
from gg_ingestion.models import DocMeta, ParsedBlock, ParsedDocument
from gg_ingestion.pipeline import _parsed_to_json


def test_parse_artifact_round_trip():
    parsed = ParsedDocument(
        meta=DocMeta(
            doc_key="SOP-004",
            doc_type="sop",
            title="Corrective and Preventive Action",
            revision="B",
            file_format="docx",
        ),
        blocks=(
            ParsedBlock(kind="heading", text="1. Purpose", section_path="1. Purpose"),
            ParsedBlock(
                kind="row",
                text="Requirement ID: REQ-001",
                fields={"Requirement ID": "REQ-001"},
                row_number=4,
            ),
        ),
        parser="docx_narrative",
        warnings=("one warning",),
        attributes={"effective_date": "30-Apr-2026"},
    )
    assert parsed_from_artifact(_parsed_to_json(parsed)) == parsed


def test_document_node_drops_absent_metadata():
    node = document_node(
        RegistryDocument(
            doc_key="CAPA-2025-007",
            doc_type="capa",
            title="Corrective and Preventive Action Record",
            content_hash="abc",
            revision=None,
            effective_from=None,
        )
    )
    assert node.label == "Document"
    assert node.key == "CAPA-2025-007"
    assert node.properties == {
        "doc_type": "capa",
        "title": "Corrective and Preventive Action Record",
    }
    dated = document_node(
        RegistryDocument(
            doc_key="SOP-004",
            doc_type="sop",
            title="CAPA SOP",
            content_hash="def",
            revision="B",
            effective_from=date(2026, 4, 30),
        )
    )
    assert dated.properties["effective_from"] == "2026-04-30"
