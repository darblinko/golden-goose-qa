"""plan_supersessions decides which revision of a document is effective and
closes out the ones it superseded; the plan feeds both the registry rows and
the Qdrant payload updates."""

from datetime import UTC, date, datetime

from gg_ingestion.registry import SupersedePlan, VersionLifecycle, plan_supersessions


def _version(
    version_id: str,
    effective_from: date | None,
    *,
    status: str = "effective",
    effective_to: date | None = None,
    created_minute: int = 0,
) -> VersionLifecycle:
    return VersionLifecycle(
        version_id=version_id,
        effective_from=effective_from,
        created_at=datetime(2026, 1, 1, 12, created_minute, tzinfo=UTC),
        status=status,
        effective_to=effective_to,
    )


def test_single_version_needs_no_plan():
    assert plan_supersessions([_version("v1", date(2024, 1, 1))]) == []


def test_older_revision_becomes_obsolete_closed_at_successor():
    plans = plan_supersessions(
        [
            _version("v-b", date(2025, 6, 1), created_minute=0),
            _version("v-a", date(2023, 2, 1), created_minute=1),
        ]
    )
    assert plans == [
        SupersedePlan(version_id="v-a", status="obsolete", effective_to=date(2025, 6, 1))
    ]


def test_settled_state_yields_empty_plan():
    versions = [
        _version("v-a", date(2023, 2, 1), status="obsolete", effective_to=date(2025, 6, 1)),
        _version("v-b", date(2025, 6, 1)),
    ]
    assert plan_supersessions(versions) == []


def test_reinstated_version_reopens_as_effective():
    """If the newest revision arrives dated earlier than a closed one, the
    ordering is by effective date, not arrival: the plan repairs both rows."""
    versions = [
        _version("v-b", date(2025, 6, 1), status="obsolete", effective_to=date(2023, 2, 1)),
        _version("v-a", date(2023, 2, 1), status="effective", created_minute=1),
    ]
    plans = plan_supersessions(versions)
    assert plans == [
        SupersedePlan(version_id="v-a", status="obsolete", effective_to=date(2025, 6, 1)),
        SupersedePlan(version_id="v-b", status="effective", effective_to=None),
    ]


def test_undated_versions_order_by_arrival():
    plans = plan_supersessions(
        [
            _version("v-1", None, created_minute=0),
            _version("v-2", None, created_minute=1),
        ]
    )
    assert plans == [SupersedePlan(version_id="v-1", status="obsolete", effective_to=None)]


def test_future_revision_leaves_predecessor_in_effect_until_its_date():
    """Publishing B ahead of its effective date must not take A out of force:
    A stays effective, closed at B's start, so the [from, to) window serves A
    today and B from its effective date."""
    versions = [
        _version("v-a", date(2026, 3, 1)),
        _version("v-b", date(2027, 1, 1), created_minute=1),
    ]
    plans = plan_supersessions(versions, today=date(2026, 10, 30))
    assert plans == [
        SupersedePlan(version_id="v-a", status="effective", effective_to=date(2027, 1, 1))
    ]


def test_predecessor_becomes_obsolete_once_successor_date_passes():
    versions = [
        _version("v-a", date(2026, 3, 1), effective_to=date(2027, 1, 1)),
        _version("v-b", date(2027, 1, 1), created_minute=1),
    ]
    plans = plan_supersessions(versions, today=date(2027, 1, 1))
    assert plans == [
        SupersedePlan(version_id="v-a", status="obsolete", effective_to=date(2027, 1, 1))
    ]
