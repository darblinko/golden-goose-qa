"""find_revision_conflict refuses a second version that reuses another version's
revision label, while allowing null/empty revisions and a retry of the same
version. This is the pure decision behind assert_unique_revision, which the
pipeline uses to quarantine repeated revision identities before indexing."""

from gg_ingestion.registry import find_revision_conflict


def test_no_conflict_when_revision_is_new():
    existing = [("v1", "A"), ("v2", "B")]
    assert find_revision_conflict(existing, "v3", "C") is None


def test_conflict_returns_the_owning_version():
    existing = [("v1", "A"), ("v2", "B")]
    assert find_revision_conflict(existing, "v3", "A") == "v1"


def test_same_version_never_conflicts_with_itself():
    # A retry of v1 that keeps revision A must be allowed.
    assert find_revision_conflict([("v1", "A")], "v1", "A") is None


def test_null_or_empty_revision_never_conflicts():
    existing = [("v1", None), ("v2", "")]
    assert find_revision_conflict(existing, "v3", None) is None
    assert find_revision_conflict(existing, "v3", "") is None


def test_unrevised_versions_coexist():
    # Two records with no revision may both exist; only concrete labels collide.
    assert find_revision_conflict([("v1", None)], "v2", None) is None
