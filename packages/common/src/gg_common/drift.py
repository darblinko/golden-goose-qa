"""Registry↔index drift classification.

Content-hash idempotency means an already-'indexed' version is never
re-processed, so a point set that silently diverges from the registry — a delete
that outran its upsert, an orphaned or partially-written generation — would
persist indefinitely. This is the pure predicate a drift scan (and the pipeline's
unchanged short-circuit) use to decide whether a version's live point count still
matches what the registry expects.
"""


def classify_drift(expected: int, actual: int) -> str | None:
    """Compare a version's expected child-chunk count (registry) against its live
    point count (index).

    - ``None``: they agree — including the childless ``0 == 0`` case, which is in
      sync, not drifted.
    - ``"missing"``: the registry expects children but the index has none —
      searchable evidence has vanished (e.g. a delete that was never followed by
      its upsert).
    - ``"mismatch"``: both are non-zero but unequal — a partial delete/upsert left
      the index over- or under-populated.
    """
    if expected == actual:
        return None
    if actual == 0:
        return "missing"
    return "mismatch"
