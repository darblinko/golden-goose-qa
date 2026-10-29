"""Unit tests for the controlled-document identity metadata gate.

A controlled document is only trustworthy audit evidence when its revision and
effective date are present and well-formed and its internal document number
agrees with its filename identity. The gate must fail such a document loudly and
must never touch record forms that are unrevised by design.
"""

import pytest
from gg_ingestion.controlled import METADATA_GATED_TYPES, enforce_controlled_metadata
from gg_ingestion.metrics import IngestGateError
from gg_ingestion.models import DocMeta


def _meta(doc_type: str, revision: str | None) -> DocMeta:
    return DocMeta(
        doc_key="SOP-004",
        doc_type=doc_type,
        title="Corrective and Preventive Action",
        revision=revision,
        file_format="docx",
    )


_GOOD_ATTRS = {
    "document_number": "SOP-004",
    "effective_date": "30-Apr-2026",
    "department": "Quality Assurance",
}


class TestControlledMetadataGate:
    def test_valid_controlled_document_passes(self):
        enforce_controlled_metadata(_meta("sop", "B"), dict(_GOOD_ATTRS))

    def test_uncontrolled_type_is_never_gated(self):
        # A CAPA record is unrevised by design; missing revision/date is fine.
        enforce_controlled_metadata(_meta("capa", None), {})

    def test_design_input_excluded_though_controlled(self):
        # PRS-100 is a controlled input published without a doc-info control block,
        # so the metadata gate must not fail it for lacking revision/effective date.
        assert "design_input" not in METADATA_GATED_TYPES
        enforce_controlled_metadata(_meta("design_input", None), {})

    def test_missing_revision_fails(self):
        with pytest.raises(IngestGateError) as err:
            enforce_controlled_metadata(_meta("sop", None), dict(_GOOD_ATTRS))
        assert err.value.gate == "controlled_metadata"

    def test_empty_revision_fails(self):
        with pytest.raises(IngestGateError):
            enforce_controlled_metadata(_meta("sop", "  "), dict(_GOOD_ATTRS))

    def test_malformed_revision_fails(self):
        with pytest.raises(IngestGateError):
            enforce_controlled_metadata(_meta("sop", "Rev A"), dict(_GOOD_ATTRS))

    def test_missing_effective_date_fails(self):
        attrs = dict(_GOOD_ATTRS)
        del attrs["effective_date"]
        with pytest.raises(IngestGateError) as err:
            enforce_controlled_metadata(_meta("sop", "B"), attrs)
        assert err.value.gate == "controlled_metadata"

    def test_malformed_effective_date_fails(self):
        attrs = {**_GOOD_ATTRS, "effective_date": "2026-04-30"}
        with pytest.raises(IngestGateError):
            enforce_controlled_metadata(_meta("sop", "B"), attrs)

    def test_missing_document_number_fails(self):
        attrs = dict(_GOOD_ATTRS)
        del attrs["document_number"]
        with pytest.raises(IngestGateError):
            enforce_controlled_metadata(_meta("sop", "B"), attrs)

    def test_conflicting_document_number_fails(self):
        attrs = {**_GOOD_ATTRS, "document_number": "SOP-009"}
        with pytest.raises(IngestGateError) as err:
            enforce_controlled_metadata(_meta("sop", "B"), attrs)
        assert "SOP-009" in str(err.value)

    def test_every_gated_type_requires_metadata(self):
        for doc_type in METADATA_GATED_TYPES:
            with pytest.raises(IngestGateError):
                enforce_controlled_metadata(_meta(doc_type, None), dict(_GOOD_ATTRS))
