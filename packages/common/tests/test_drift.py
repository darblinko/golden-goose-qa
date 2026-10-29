"""classify_drift is the pure decision behind the registry↔Qdrant drift scan and
the pipeline's unchanged short-circuit: it says whether a version's live point
count still matches what the registry expects."""

from gg_common.drift import classify_drift


def test_equal_counts_are_in_sync():
    assert classify_drift(12, 12) is None


def test_childless_version_is_in_sync_not_drifted():
    # A parent-only document expects zero child points; zero live points agree.
    assert classify_drift(0, 0) is None


def test_no_live_points_is_missing_evidence():
    # The registry expects children but Qdrant has none — the worst case, a
    # delete that outran its upsert leaving nothing searchable.
    assert classify_drift(5, 0) == "missing"


def test_unequal_nonzero_counts_are_a_mismatch():
    assert classify_drift(5, 3) == "mismatch"
    assert classify_drift(3, 5) == "mismatch"
