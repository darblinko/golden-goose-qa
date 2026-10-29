"""Action priority spot-checks against the bundled synthetic example table.

The example is not the AIAG-VDA table; see gg_common.actionpriority.
"""

import pytest
from gg_synthdata.model import ap_from_sod
from gg_synthdata.world import build_world


@pytest.mark.parametrize(
    ("severity", "occurrence", "detection", "expected"),
    [
        (9, 4, 5, "H"),
        (10, 2, 7, "H"),
        (8, 9, 9, "H"),
        (10, 2, 6, "M"),
        (9, 3, 4, "M"),
        (2, 9, 9, "M"),
        (8, 3, 4, "L"),
        (9, 2, 3, "L"),
        (1, 1, 1, "L"),
    ],
)
def test_ap_from_sod(severity, occurrence, detection, expected):
    assert ap_from_sod(severity, occurrence, detection) == expected


def test_fmea_rows_use_table_ap_except_seeded_defect():
    world = build_world(42)
    for row in world.pfmea_rows:
        assert row.ap_recorded == ap_from_sod(row.severity, row.occurrence, row.detection)
    for row in world.dfmea_rows:
        assert row.ap_correct == ap_from_sod(row.severity, row.occurrence, row.detection)
