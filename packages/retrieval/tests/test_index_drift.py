"""index_drift walks every indexed version and reports the ones whose live Qdrant
point count no longer matches the registry's expected child-chunk count."""

from types import SimpleNamespace
from typing import Any, cast

from gg_retrieval.drift import index_drift


class _Row:
    def __init__(self, version_id: str, doc_key: str, expected: int) -> None:
        self.version_id = version_id
        self.doc_key = doc_key
        self.expected = expected


class _Result:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def all(self) -> list[_Row]:
        return self._rows


class _Session:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, *args: Any, **kwargs: Any) -> _Result:
        return _Result(self._rows)


class _Qdrant:
    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts

    async def count(self, *, collection_name: str, count_filter: Any, exact: bool) -> Any:
        version_id = count_filter.must[0].match.value
        return SimpleNamespace(count=self._counts[version_id])


async def test_reports_missing_and_mismatch_and_ignores_in_sync():
    rows = [
        _Row("v1", "SOP-1", 3),  # in sync
        _Row("v2", "SOP-2", 4),  # missing: expects 4, has 0
        _Row("v3", "SOP-3", 2),  # mismatch: expects 2, has 5
        _Row("v4", "REC-1", 0),  # childless, in sync
    ]
    qdrant = _Qdrant({"v1": 3, "v2": 0, "v3": 5, "v4": 0})

    report = await index_drift(
        cast(Any, qdrant), cast(Any, lambda: _Session(rows)), collection="gg_chunks"
    )

    assert report["versions_checked"] == 4
    assert report["in_sync"] is False
    kinds = {d["version_id"]: d["kind"] for d in report["drifted"]}
    assert kinds == {"v2": "missing", "v3": "mismatch"}


async def test_in_sync_when_every_version_matches():
    rows = [_Row("v1", "SOP-1", 3), _Row("v2", "REC-1", 0)]
    qdrant = _Qdrant({"v1": 3, "v2": 0})

    report = await index_drift(
        cast(Any, qdrant), cast(Any, lambda: _Session(rows)), collection="gg_chunks"
    )

    assert report["in_sync"] is True
    assert report["drifted"] == []
