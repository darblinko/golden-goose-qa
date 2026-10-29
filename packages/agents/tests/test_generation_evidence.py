"""Revision-provenance gate and the evidence dicts that carry version identity.

The citation contract requires every answer to cite doc id, revision, and page.
A controlled document whose revision is missing cannot be cited that way, so it
must never become generation evidence. Point-in-time records and synthetic
tool/external parents are exempt — they legitimately have no revision.
"""

from typing import Any, cast

from gg_agents.nodes import _generation_parents, _has_required_revision
from gg_agents.state import AgentState, citation_view, parent_to_dict
from gg_retrieval.models import ParentContext


def _internal(doc_type: str, revision: str | None) -> dict[str, Any]:
    return {
        "provenance": "internal",
        "doc_type": doc_type,
        "revision": revision,
        "text": "body",
        "citation": "c",
    }


def test_controlled_doc_missing_revision_is_not_evidence():
    assert not _has_required_revision(_internal("sop", None))
    assert not _has_required_revision(_internal("sop", ""))
    assert not _has_required_revision(_internal("sop", "   "))
    assert _has_required_revision(_internal("sop", "B"))


def test_timeless_record_without_revision_is_evidence():
    # A complaint/NCR/CAPA is a dated fact, not a versioned document.
    assert _has_required_revision(_internal("complaint", None))
    assert _has_required_revision(_internal("ncr", ""))


def test_synthetic_parents_without_revision_are_evidence():
    assert _has_required_revision(_internal("tool_result", ""))
    assert _has_required_revision(_internal("external_result", ""))


def test_external_provenance_never_gated():
    assert _has_required_revision(
        {"provenance": "external", "doc_type": "external_result", "revision": ""}
    )


def test_generation_parents_drops_unrevised_controlled_doc():
    state = cast(
        AgentState,
        {"parents": [_internal("sop", None), _internal("sop", "B")], "external_parents": []},
    )
    parents = _generation_parents(state)
    assert len(parents) == 1
    assert parents[0]["revision"] == "B"


def test_generation_parents_appends_external_after_filter():
    external = {"provenance": "external", "doc_type": "external_result", "revision": ""}
    state = cast(AgentState, {"parents": [_internal("sop", None)], "external_parents": [external]})
    # the only internal parent is dropped; external evidence still appears
    assert _generation_parents(state) == [external]


def _parent_context() -> ParentContext:
    return ParentContext(
        parent_id="p1",
        doc_key="SOP-004",
        doc_type="sop",
        title="CAPA",
        revision="B",
        section_path="3. Procedure",
        text="parent body",
        context_header="h",
        best_child_score=0.9,
        page=4,
        version_id="ver-123",
        matched_child_text="the matched sentence",
    )


def test_parent_to_dict_carries_version_and_matched_child():
    d = parent_to_dict(_parent_context())
    assert d["version_id"] == "ver-123"
    assert d["matched_child_text"] == "the matched sentence"


def test_citation_view_exposes_version_id():
    view = citation_view(parent_to_dict(_parent_context()), 1)
    assert view["version_id"] == "ver-123"
    assert view["revision"] == "B"
