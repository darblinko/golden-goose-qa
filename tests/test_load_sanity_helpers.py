"""Pure helpers of the load sanity script (the load run itself is manual)."""

import importlib.util
import os
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "load_sanity.py"
_spec = importlib.util.spec_from_file_location("load_sanity", _SCRIPT)
assert _spec is not None and _spec.loader is not None
load_sanity = importlib.util.module_from_spec(_spec)
sys.modules["load_sanity"] = load_sanity
_spec.loader.exec_module(load_sanity)


def test_parse_sse_pairs_events_with_payloads():
    lines = [
        "event: step",
        'data: {"node": "route"}',
        "",
        "event: done",
        'data: {"verdict": "grounded"}',
        "",
    ]
    assert load_sanity.parse_sse(lines) == [
        ("step", {"node": "route"}),
        ("done", {"verdict": "grounded"}),
    ]


def test_percentile_bounds():
    values = [10.0, 20.0, 30.0, 40.0]
    assert load_sanity.percentile(values, 0) == 10.0
    assert load_sanity.percentile(values, 100) == 40.0
    assert load_sanity.percentile([], 50) == 0.0


def test_parse_mem_mib_units():
    assert load_sanity.parse_mem_mib("512MiB / 1GiB") == 512.0
    assert load_sanity.parse_mem_mib("1.5GiB / 2GiB") == 1536.0
    assert load_sanity.parse_mem_mib("2048KiB / 1GiB") == 2.0
    assert load_sanity.parse_mem_mib("garbage") == 0.0


def test_parse_percent():
    assert load_sanity.parse_percent("87.5%") == 87.5
    assert load_sanity.parse_percent("--") == 0.0


def test_memory_alerts_flag_only_above_fraction():
    peaks = {
        "goldengoose-postgres": (950.0, 92.7),
        "goldengoose-qdrant": (700.0, 45.0),
    }
    alerts = load_sanity.memory_alerts(peaks)
    assert len(alerts) == 1
    assert "goldengoose-postgres" in alerts[0] and "92.7%" in alerts[0]


def test_summarize_separates_errors_from_latencies():
    turns = [
        load_sanity.TurnStats(0, 0, 100.0, 900.0, "grounded", None),
        load_sanity.TurnStats(0, 1, 150.0, 1100.0, "grounded", None),
        load_sanity.TurnStats(1, 0, 0.0, 5000.0, "", "ReadTimeout: boom"),
    ]
    summary = load_sanity.summarize(turns)
    assert summary["turns"] == 3
    assert summary["errors"] == ["session 1 turn 0: ReadTimeout: boom"]
    assert summary["verdicts"] == {"grounded": 2}
    # The failed turn must not pollute the latency percentiles.
    assert summary["turn_ms"]["max"] == 1100.0


def _full_container_peaks() -> dict[str, tuple[float, float]]:
    return {f"goldengoose-{service}-1": (100.0, 10.0) for service in load_sanity.REQUIRED_SERVICES}


def test_missing_members_flags_absent_container_and_process():
    # Everything observed -> nothing missing.
    complete = _full_container_peaks()
    procs = {load_sanity.API_MEMBER: 300.0, load_sanity.DERIVE_MEMBER: 400.0}
    assert load_sanity.missing_members(complete, procs, skip_derive=False) == []
    # Drop qdrant and the API sample -> both reported.
    partial = {k: v for k, v in complete.items() if "qdrant" not in k}
    missing = load_sanity.missing_members(partial, {}, skip_derive=False)
    assert "container:qdrant" in missing
    assert "process:api" in missing
    assert "process:derive" in missing


def test_missing_members_skips_derive_when_not_run():
    complete = _full_container_peaks()
    procs = {load_sanity.API_MEMBER: 300.0}  # no derive
    assert load_sanity.missing_members(complete, procs, skip_derive=True) == []
    assert load_sanity.missing_members(complete, procs, skip_derive=False) == ["process:derive"]


def test_zero_sample_counts_as_missing():
    # A member present in the dict but never actually measured (0 MiB) is not
    # proof of observation and must still be flagged.
    complete = _full_container_peaks()
    procs = {load_sanity.API_MEMBER: 0.0, load_sanity.DERIVE_MEMBER: 400.0}
    assert load_sanity.missing_members(complete, procs, skip_derive=False) == ["process:api"]


def test_fleet_total_sums_containers_and_processes():
    containers = {"goldengoose-postgres-1": (600.0, 30.0), "goldengoose-qdrant-1": (400.0, 20.0)}
    procs = {"api": 300.0, "derive": 700.0}
    assert load_sanity.fleet_total_mib(containers, procs) == 2000.0


def test_fleet_budget_alert_triggers_only_over_budget():
    under = {"c": (float(load_sanity.FLEET_MEMORY_BUDGET_MIB - 1), 50.0)}
    assert load_sanity.fleet_budget_alert(under, {}) is None
    over = {"c": (float(load_sanity.FLEET_MEMORY_BUDGET_MIB), 50.0)}
    assert load_sanity.fleet_budget_alert(over, {"api": 1.0}) is not None


def test_process_rss_of_this_interpreter_is_positive():
    # The running test process must report a non-trivial resident set, proving
    # the /proc sampling path works on this host.
    assert load_sanity._read_rss_mib(os.getpid()) > 0.0
    assert os.getpid() in load_sanity._process_tree(os.getpid())
    assert load_sanity.tree_rss_mib(os.getpid()) >= load_sanity._read_rss_mib(os.getpid())


def test_read_rss_of_dead_pid_is_zero():
    # PID 2^31-1 will not exist; a gone process reports 0.0, not a crash.
    assert load_sanity._read_rss_mib(2**31 - 1) == 0.0
