from datetime import UTC, date, datetime

from gg_retrieval.search import ANY_STATUS, build_filter
from qdrant_client import models

_MOMENT = datetime(2024, 3, 15, tzinfo=UTC)


def _conditions(flt: models.Filter | None) -> dict[str, object]:
    assert flt is not None
    assert isinstance(flt.must, list)
    out: dict[str, object] = {}
    for cond in flt.must:
        assert isinstance(cond, models.FieldCondition)
        assert isinstance(cond.match, models.MatchValue)
        out[cond.key] = cond.match.value
    return out


def test_no_criteria_returns_none():
    assert build_filter() is None


def test_status_only():
    assert _conditions(build_filter(status="effective")) == {"status": "effective"}


def test_any_status_sentinel_skips_condition():
    assert build_filter(status=ANY_STATUS) is None


def test_all_criteria_combined():
    conditions = _conditions(build_filter(doc_type="sop", doc_key="SOP-004", status="effective"))
    assert conditions == {"doc_type": "sop", "doc_key": "SOP-004", "status": "effective"}


def test_revision_predicate_added():
    # An explicit revision becomes an exact keyword match on the indexed
    # 'revision' payload field, so a scoped query cannot leak a neighbor revision.
    assert _conditions(build_filter(doc_key="SOP-004", revision="A")) == {
        "doc_key": "SOP-004",
        "revision": "A",
    }


def test_revision_is_a_single_exact_condition():
    flt = build_filter(doc_key="SOP-004", revision="A")
    assert flt is not None
    assert isinstance(flt.must, list)
    assert len(flt.must) == 2  # doc_key + revision, nothing else


def test_empty_revision_adds_no_condition():
    assert build_filter(revision="") is None
    assert _conditions(build_filter(doc_key="SOP-004", revision="")) == {"doc_key": "SOP-004"}


def _as_of_should(flt: models.Filter) -> models.Filter:
    """The single as-of clause build_filter appends: a should of
    (timeless doc_type match) OR (controlled-in-effect window)."""
    assert isinstance(flt.must, list)
    for cond in flt.must:
        if isinstance(cond, models.Filter) and cond.should is not None:
            return cond
    raise AssertionError("no as-of should-clause")


def _controlled_window(flt: models.Filter) -> models.Filter:
    should = _as_of_should(flt).should
    assert isinstance(should, list)
    window = should[1]
    assert isinstance(window, models.Filter)
    return window


def test_as_of_bounds_controlled_effective_window():
    flt = build_filter(as_of=date(2024, 3, 15))
    assert flt is not None
    window = _controlled_window(flt)
    assert isinstance(window.must, list)

    # A real effective_from on or before the moment — no empty-field escape.
    start = window.must[0]
    assert isinstance(start, models.FieldCondition)
    assert start.key == "effective_from"
    assert start.range is not None
    assert start.range.lte == _MOMENT
    assert start.range.gt is None

    # effective_to: still in effect (empty) OR strictly after the moment.
    end = window.must[1]
    assert isinstance(end, models.Filter)
    assert isinstance(end.should, list)
    empty, ranged = end.should
    assert isinstance(empty, models.IsEmptyCondition)
    assert empty.is_empty.key == "effective_to"
    assert isinstance(ranged, models.FieldCondition)
    assert ranged.range is not None
    assert ranged.range.gt == _MOMENT


def test_as_of_excludes_undated_controlled_revision():
    """The controlled-document branch gates effective_from with a range, never
    an IsEmpty escape — so a null-effective_from (obsolete/undated) revision
    cannot match an as-of date and be returned as current evidence."""
    flt = build_filter(as_of=date(2024, 3, 15))
    assert flt is not None
    window = _controlled_window(flt)
    assert isinstance(window.must, list)
    start = window.must[0]
    assert isinstance(start, models.FieldCondition)  # a range gate, never IsEmpty
    assert start.key == "effective_from"


def _record_branch(flt: models.Filter) -> models.Filter:
    branch = _as_of_should(flt).should[0]  # type: ignore[index]
    assert isinstance(branch, models.Filter)
    assert isinstance(branch.must, list)
    return branch


def test_as_of_admits_timeless_record_types():
    """Records without a controlled effective interval (complaints, NCRs,
    CAPAs, ...) match on doc_type; training_matrix is NOT among them because it
    is a versioned document, not a point-in-time record."""
    from gg_retrieval.search import AS_OF_TIMELESS_DOC_TYPES

    flt = build_filter(as_of=date(2024, 3, 15))
    assert flt is not None
    doc_type_cond = _record_branch(flt).must[0]  # type: ignore[index]
    assert isinstance(doc_type_cond, models.FieldCondition)
    assert doc_type_cond.key == "doc_type"
    assert isinstance(doc_type_cond.match, models.MatchAny)
    assert set(doc_type_cond.match.any) == set(AS_OF_TIMELESS_DOC_TYPES)
    assert {"complaint", "ncr", "capa", "mdr"} <= set(doc_type_cond.match.any)
    assert "training_matrix" not in doc_type_cond.match.any


def test_training_matrix_is_not_timeless():
    from gg_retrieval.search import AS_OF_TIMELESS_DOC_TYPES

    assert "training_matrix" not in AS_OF_TIMELESS_DOC_TYPES


def test_as_of_timeless_record_gated_by_event_date():
    """A record dated after the as-of moment is out of scope; an undated record
    stays permissive. The record branch pairs the doc_type match with an
    effective_from gate: empty OR <= moment."""
    flt = build_filter(as_of=date(2024, 3, 15))
    assert flt is not None
    gate = _record_branch(flt).must[1]  # type: ignore[index]
    assert isinstance(gate, models.Filter)
    assert isinstance(gate.should, list)
    empty, ranged = gate.should
    assert isinstance(empty, models.IsEmptyCondition)
    assert empty.is_empty.key == "effective_from"
    assert isinstance(ranged, models.FieldCondition)
    assert ranged.key == "effective_from"
    assert ranged.range is not None
    assert ranged.range.lte == _MOMENT
    assert ranged.range.gt is None


def test_as_of_composes_with_doc_key():
    flt = build_filter(doc_key="SOP-004", as_of=date(2024, 3, 15))
    assert flt is not None
    assert isinstance(flt.must, list)
    # doc_key condition + the single as-of should-clause.
    assert len(flt.must) == 2


def test_now_adds_effective_window_alongside_status():
    """Default retrieval (status=effective) also binds to the revision in effect
    now: the same controlled effective-interval window an as-of query builds."""
    flt = build_filter(status="effective", now=date(2024, 3, 15))
    assert flt is not None
    assert _conditions_of_type(flt) == {"status": "effective"}
    window = _controlled_window(flt)
    assert isinstance(window.must, list)
    start = window.must[0]
    assert isinstance(start, models.FieldCondition)
    assert start.key == "effective_from"
    assert start.range is not None and start.range.lte == _MOMENT


def test_as_of_takes_precedence_over_now():
    # If both are supplied, as_of governs the single time window; now is ignored.
    flt = build_filter(as_of=date(2024, 3, 15), now=date(2000, 1, 1))
    assert flt is not None
    window = _controlled_window(flt)
    assert isinstance(window.must, list)
    start = window.must[0]
    assert isinstance(start, models.FieldCondition)
    assert start.range is not None and start.range.lte == _MOMENT  # the as_of moment


def _conditions_of_type(flt: models.Filter) -> dict[str, object]:
    out: dict[str, object] = {}
    for cond in flt.must:  # type: ignore[union-attr]
        if isinstance(cond, models.FieldCondition) and isinstance(cond.match, models.MatchValue):
            out[cond.key] = cond.match.value
    return out


def _level_condition(flt: models.Filter | None) -> models.FieldCondition:
    assert flt is not None
    assert isinstance(flt.must, list)
    for cond in flt.must:
        if isinstance(cond, models.FieldCondition) and cond.key == "access_level":
            return cond
    raise AssertionError("no access_level condition")


def test_allowed_levels_becomes_match_any():
    cond = _level_condition(build_filter(allowed_levels=("general",)))
    assert isinstance(cond.match, models.MatchAny)
    assert cond.match.any == ["general"]


def test_allowed_levels_none_adds_no_condition():
    assert build_filter(allowed_levels=None) is None


def test_allowed_levels_composes_with_doc_type():
    flt = build_filter(doc_type="complaint", allowed_levels=("general", "restricted"))
    cond = _level_condition(flt)
    assert isinstance(cond.match, models.MatchAny)
    assert cond.match.any == ["general", "restricted"]
    assert flt is not None
    assert isinstance(flt.must, list)
    assert len(flt.must) == 2
