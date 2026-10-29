"""FMEA Action Priority (AP) lookup from a user-supplied table file.

The AIAG-VDA FMEA Handbook Action Priority table is copyrighted and is not
distributed with this repository. A site supplies its table, transcribed from
its licensed copy of the handbook, as a JSON file named by GG_AP_TABLE_PATH.
When that setting is unset, the bundled synthetic example table
(data/ap_table_synthetic_example.json) is used. The example is invented for
the tests and the synthetic demo corpus; it is not the AIAG-VDA table.

This is the single canonical AP implementation: the synthetic corpus generator
uses it to fill FMEA sheets and the registers warehouse uses it to recompute AP
from S/O/D, so a sheet-vs-recomputed mismatch is a data defect, never a table
disagreement, as long as both run with the same table.

Table file format (JSON object):
    name       non-empty string
    synthetic  true or false
    bands      {"severity": [...], "occurrence": [...], "detection": [...]}:
               inclusive upper bounds of each band, strictly increasing integers
               between 1 and 10, the last one 10. [1, 3, 6, 8, 10] means bands
               {1}, {2-3}, {4-6}, {7-8}, {9-10}.
    levels     levels[severity_band][occurrence_band][detection_band], each
               "H", "M" or "L"; the nesting must match the band counts.
Other keys (notice, rule) are ignored.
"""

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

from gg_common.settings import get_settings

logger = logging.getLogger(__name__)

SYNTHETIC_EXAMPLE_PATH = Path(__file__).parent / "data" / "ap_table_synthetic_example.json"
AP_LEVELS = ("H", "M", "L")
_AXES = ("severity", "occurrence", "detection")


class ActionPriorityTableError(ValueError):
    """An AP table file is missing, unreadable or malformed."""


@dataclass(frozen=True)
class ActionPriorityTable:
    name: str
    synthetic: bool
    severity_bounds: tuple[int, ...]
    occurrence_bounds: tuple[int, ...]
    detection_bounds: tuple[int, ...]
    levels: tuple[tuple[tuple[str, ...], ...], ...]

    def lookup(self, severity: int, occurrence: int, detection: int) -> str:
        """Return the AP level ('H', 'M' or 'L') for 1-10 S/O/D ratings."""
        s_band = _band(severity, self.severity_bounds, "severity")
        o_band = _band(occurrence, self.occurrence_bounds, "occurrence")
        d_band = _band(detection, self.detection_bounds, "detection")
        return self.levels[s_band][o_band][d_band]


def _band(value: int, bounds: tuple[int, ...], axis: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not (1 <= value <= 10):
        raise ValueError(f"AP input '{axis}' must be an integer 1-10, got {value!r}")
    for index, upper in enumerate(bounds):
        if value <= upper:
            return index
    raise ValueError(f"AP input '{axis}' must be an integer 1-10, got {value!r}")


def _fail(source: str, reason: str) -> ActionPriorityTableError:
    return ActionPriorityTableError(f"AP table {source}: {reason}")


def _parse_bounds(raw: object, axis: str, source: str) -> tuple[int, ...]:
    where = f"bands.{axis}"
    if not isinstance(raw, list) or not raw:
        raise _fail(source, f"{where} must be a non-empty list of band upper bounds")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in raw):
        raise _fail(source, f"{where} must contain integers, got {raw!r}")
    if not all(1 <= v <= 10 for v in raw):
        raise _fail(source, f"{where} bounds must be between 1 and 10, got {raw!r}")
    if any(later <= earlier for earlier, later in pairwise(raw)):
        raise _fail(source, f"{where} bounds must be strictly increasing, got {raw!r}")
    if raw[-1] != 10:
        raise _fail(source, f"{where} bounds must end at 10, got {raw!r}")
    return tuple(raw)


def _parse_levels(
    raw: object, shape: tuple[int, int, int], source: str
) -> tuple[tuple[tuple[str, ...], ...], ...]:
    n_sev, n_occ, n_det = shape
    if not isinstance(raw, list) or len(raw) != n_sev:
        raise _fail(source, f"levels must have {n_sev} severity rows")
    rows = []
    for s, by_occurrence in enumerate(raw):
        if not isinstance(by_occurrence, list) or len(by_occurrence) != n_occ:
            raise _fail(source, f"levels[{s}] must have {n_occ} occurrence rows")
        row = []
        for o, by_detection in enumerate(by_occurrence):
            where = f"levels[{s}][{o}]"
            if not isinstance(by_detection, list) or len(by_detection) != n_det:
                raise _fail(source, f"{where} must have {n_det} detection values")
            bad = [v for v in by_detection if v not in AP_LEVELS]
            if bad:
                raise _fail(source, f"{where} values must be one of H, M, L, got {bad!r}")
            row.append(tuple(by_detection))
        rows.append(tuple(row))
    return tuple(rows)


def parse_table(raw: object, source: str) -> ActionPriorityTable:
    """Validate a decoded table document; raise ActionPriorityTableError on any defect."""
    if not isinstance(raw, dict):
        raise _fail(source, "must be a JSON object")
    for key in ("name", "synthetic", "bands", "levels"):
        if key not in raw:
            raise _fail(source, f"missing key '{key}'")
    name, synthetic, bands = raw["name"], raw["synthetic"], raw["bands"]
    if not isinstance(name, str) or not name.strip():
        raise _fail(source, "'name' must be a non-empty string")
    if not isinstance(synthetic, bool):
        raise _fail(source, "'synthetic' must be true or false")
    if not isinstance(bands, dict):
        raise _fail(source, "'bands' must be an object with severity, occurrence, detection")
    bounds = {}
    for axis in _AXES:
        if axis not in bands:
            raise _fail(source, f"missing bands.{axis}")
        bounds[axis] = _parse_bounds(bands[axis], axis, source)
    shape = (len(bounds["severity"]), len(bounds["occurrence"]), len(bounds["detection"]))
    return ActionPriorityTable(
        name=name,
        synthetic=synthetic,
        severity_bounds=bounds["severity"],
        occurrence_bounds=bounds["occurrence"],
        detection_bounds=bounds["detection"],
        levels=_parse_levels(raw["levels"], shape, source),
    )


def load_table(path: Path) -> ActionPriorityTable:
    """Read and validate an AP table JSON file."""
    source = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _fail(source, f"cannot read file ({exc.strerror or exc})") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _fail(source, f"not valid JSON ({exc.msg} at line {exc.lineno})") from exc
    return parse_table(raw, source)


@lru_cache(maxsize=1)
def configured_table() -> ActionPriorityTable:
    """The table named by GG_AP_TABLE_PATH, or the synthetic example when unset."""
    configured = get_settings().ap_table_path
    if configured:
        table = load_table(Path(configured))
        logger.info("action priority table loaded: %s (%s)", table.name, configured)
        return table
    logger.warning(
        "GG_AP_TABLE_PATH is not set; using the synthetic example AP table, which is "
        "not the AIAG-VDA table. Supply your licensed table for real FMEA work."
    )
    return load_table(SYNTHETIC_EXAMPLE_PATH)


def compute_action_priority(
    severity: int,
    occurrence: int,
    detection: int,
    table: ActionPriorityTable | None = None,
) -> str:
    """Return the Action Priority 'H', 'M' or 'L' for 1-10 S/O/D ratings.

    Uses `table` when given, otherwise the configured table.
    """
    return (table or configured_table()).lookup(severity, occurrence, detection)
