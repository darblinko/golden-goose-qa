"""Load sanity: concurrent chat sessions against the API while the ingestion
pipeline's derive stage rebuilds the graph and warehouse, with memory sampling
across the whole fleet — docker services *and* the host processes doing the
work.

    uv run python scripts/load_sanity.py                 # starts its own API
    uv run python scripts/load_sanity.py --api-url http://localhost:8000 --api-pid 1234

The API and `gg-ingest derive` run as host processes, not containers, so
sampling only `goldengoose-*` containers would omit the two processes that
generate the load — the "10 GB fleet proof" would then exclude its heaviest
members. Both are sampled by PID (resident set of the process subtree). The gate
fails when any chat turn errors, the concurrent derive fails, any expected
member is never observed, any container peaks above its per-limit alert
fraction, or the summed fleet peak exceeds the single-host budget.
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QA = REPO_ROOT / "data" / "synthetic" / "qa" / "smoke_qa.json"
DEFAULT_SESSIONS = 10
DEFAULT_TURNS = 2
OWN_API_PORT = 8600
TURN_TIMEOUT_SECONDS = 180.0
READY_TIMEOUT_SECONDS = 90.0
MEMORY_ALERT_FRACTION = 0.9
CONTAINER_PREFIX = "goldengoose-"
# The single-host budget the load run exists to defend (docstring "10 GB").
FLEET_MEMORY_BUDGET_MIB = 10 * 1024
# Core services that must each be observed for the sample to be trustworthy; a
# container name is goldengoose-<service>-N, so a substring match identifies it.
REQUIRED_SERVICES = ("postgres", "qdrant", "neo4j", "seaweedfs")
API_MEMBER = "api"
DERIVE_MEMBER = "derive"


@dataclass(frozen=True)
class TurnStats:
    session: int
    turn: int
    first_event_ms: float
    total_ms: float
    verdict: str
    error: str | None


def parse_sse(lines: list[str]) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name, data = None, []
    for line in lines:
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data.append(line.split(":", 1)[1].strip())
        elif not line.strip() and name is not None:
            events.append((name, json.loads("".join(data)) if data else {}))
            name, data = None, []
    return events


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((p / 100) * (len(ordered) - 1))
    return ordered[index]


def parse_mem_mib(mem_usage: str) -> float:
    """docker stats MemUsage like '512.5MiB / 1GiB' -> used MiB."""
    used = mem_usage.split("/")[0].strip()
    scales = {"KiB": 1 / 1024, "MiB": 1.0, "GiB": 1024.0, "B": 1 / (1024 * 1024)}
    for unit, scale in scales.items():
        if used.endswith(unit):
            return float(used.removesuffix(unit)) * scale
    return 0.0


def parse_percent(mem_perc: str) -> float:
    try:
        return float(mem_perc.strip().removesuffix("%"))
    except ValueError:
        return 0.0


def memory_alerts(peaks: dict[str, tuple[float, float]]) -> list[str]:
    limit = MEMORY_ALERT_FRACTION * 100
    return [
        f"{name} peaked at {mib:.0f} MiB ({pct:.1f}% of its limit, alert at {limit:.0f}%)"
        for name, (mib, pct) in sorted(peaks.items())
        if pct > limit
    ]


def _read_rss_mib(pid: int) -> float:
    """Resident set of a single process, MiB, from /proc. 0.0 if it is gone."""
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024  # value is in kB
    except (OSError, ValueError, IndexError):
        return 0.0
    return 0.0


def _process_tree(pid: int) -> list[int]:
    """A pid and every descendant, so a process that forks workers (uvicorn,
    derive) is measured whole rather than by its supervisor alone."""
    children: dict[int, list[int]] = {}
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            content = stat.read_text()
            # comm (field 2) is parenthesized and may contain spaces; ppid is
            # the second field after the closing paren.
            after = content[content.rfind(")") + 1 :].split()
            child = int(stat.parent.name)
            parent = int(after[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(parent, []).append(child)
    tree, stack = [], [pid]
    while stack:
        current = stack.pop()
        tree.append(current)
        stack.extend(children.get(current, []))
    return tree


def tree_rss_mib(pid: int) -> float:
    return sum(_read_rss_mib(p) for p in _process_tree(pid))


def missing_members(
    container_peaks: dict[str, tuple[float, float]],
    proc_peaks: dict[str, float],
    *,
    skip_derive: bool,
) -> list[str]:
    """Expected members that were never observed. A missing sample means the
    budget was not actually proven, so it must fail rather than pass quietly."""
    missing = []
    for service in REQUIRED_SERVICES:
        if not any(service in name for name in container_peaks):
            missing.append(f"container:{service}")
    if proc_peaks.get(API_MEMBER, 0.0) <= 0.0:
        missing.append(f"process:{API_MEMBER}")
    if not skip_derive and proc_peaks.get(DERIVE_MEMBER, 0.0) <= 0.0:
        missing.append(f"process:{DERIVE_MEMBER}")
    return missing


def fleet_total_mib(
    container_peaks: dict[str, tuple[float, float]], proc_peaks: dict[str, float]
) -> float:
    return sum(mib for mib, _ in container_peaks.values()) + sum(proc_peaks.values())


def fleet_budget_alert(
    container_peaks: dict[str, tuple[float, float]], proc_peaks: dict[str, float]
) -> str | None:
    total = fleet_total_mib(container_peaks, proc_peaks)
    if total > FLEET_MEMORY_BUDGET_MIB:
        return f"fleet peak {total:.0f} MiB exceeds the {FLEET_MEMORY_BUDGET_MIB} MiB host budget"
    return None


def summarize(turns: list[TurnStats]) -> dict[str, object]:
    total = [t.total_ms for t in turns if t.error is None]
    first = [t.first_event_ms for t in turns if t.error is None]
    verdicts: dict[str, int] = {}
    for t in turns:
        if t.error is None:
            verdicts[t.verdict] = verdicts.get(t.verdict, 0) + 1
    return {
        "turns": len(turns),
        "errors": [f"session {t.session} turn {t.turn}: {t.error}" for t in turns if t.error],
        "verdicts": verdicts,
        "first_event_ms": {"p50": percentile(first, 50), "p95": percentile(first, 95)},
        "turn_ms": {
            "p50": percentile(total, 50),
            "p95": percentile(total, 95),
            "max": max(total, default=0.0),
        },
    }


def load_questions(qa_path: Path) -> list[str]:
    data = json.loads(qa_path.read_text())
    items = data["items"] if isinstance(data, dict) else data
    questions = [item["question"] for item in items]
    if not questions:
        raise SystemExit(f"no questions in {qa_path}")
    return questions


async def _run_turn(
    client: httpx.AsyncClient, thread_id: str, question: str, session: int, turn: int
) -> TurnStats:
    started = time.monotonic()
    first_ms, verdict, error = 0.0, "", None
    try:
        async with client.stream(
            "POST", f"/threads/{thread_id}/messages", json={"content": question}
        ) as response:
            response.raise_for_status()
            lines = []
            async for line in response.aiter_lines():
                if not first_ms and line.strip():
                    first_ms = (time.monotonic() - started) * 1000
                lines.append(line)
        events = dict(parse_sse(lines))
        if "error" in events:
            error = events["error"].get("detail", "agent error")
        elif "done" not in events:
            error = "stream ended without a done event"
        else:
            verdict = events["done"].get("verdict", "")
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
    return TurnStats(
        session=session,
        turn=turn,
        first_event_ms=first_ms,
        total_ms=(time.monotonic() - started) * 1000,
        verdict=verdict,
        error=error,
    )


async def _run_session(
    base_url: str, session: int, questions: list[str], turns: int
) -> list[TurnStats]:
    async with httpx.AsyncClient(base_url=base_url, timeout=TURN_TIMEOUT_SECONDS) as client:
        minted = await client.post(
            "/auth/dev-token", json={"email": f"load-{session}@example.com", "role": "qa_user"}
        )
        minted.raise_for_status()
        client.headers["Authorization"] = f"Bearer {minted.json()['token']}"
        created = await client.post("/threads", json={})
        created.raise_for_status()
        thread_id = created.json()["id"]
        results = []
        for turn in range(turns):
            question = questions[(session * turns + turn) % len(questions)]
            results.append(await _run_turn(client, thread_id, question, session, turn))
        return results


async def _sample_docker(peaks: dict[str, tuple[float, float]]) -> None:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "stats",
        "--no-stream",
        "--format",
        "{{json .}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    for line in out.decode().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = row.get("Name", "")
        if not name.startswith(CONTAINER_PREFIX):
            continue
        mib = parse_mem_mib(row.get("MemUsage", ""))
        pct = parse_percent(row.get("MemPerc", ""))
        prior = peaks.get(name, (0.0, 0.0))
        peaks[name] = (max(prior[0], mib), max(prior[1], pct))


async def _sample_memory(
    peaks: dict[str, tuple[float, float]],
    proc_peaks: dict[str, float],
    pids: dict[str, int],
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        await _sample_docker(peaks)
        # Sample the host processes too; pids grows as derive launches mid-run.
        for label, pid in list(pids.items()):
            proc_peaks[label] = max(proc_peaks.get(label, 0.0), tree_rss_mib(pid))
        try:
            await asyncio.wait_for(stop.wait(), timeout=2.0)
        except TimeoutError:
            continue


async def _run_derive(pids: dict[str, int]) -> tuple[int, float]:
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        "gg-ingest", "derive", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    pids[DERIVE_MEMBER] = proc.pid  # register so the sampler measures its memory
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        print(f"derive stderr: {stderr.decode(errors='replace')[-2000:]}", file=sys.stderr)
    return proc.returncode or 0, time.monotonic() - started


async def _wait_ready(base_url: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                if (await client.get("/ready")).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1.0)
    raise SystemExit(f"API at {base_url} did not become ready in {READY_TIMEOUT_SECONDS:.0f}s")


def _start_api() -> tuple[subprocess.Popen, str]:
    base_url = f"http://127.0.0.1:{OWN_API_PORT}"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "goldengoose_api.main:app",
            "--port",
            str(OWN_API_PORT),
            "--log-level",
            "warning",
        ],
        cwd=REPO_ROOT,
    )
    return proc, base_url


async def run_load(
    base_url: str,
    sessions: int,
    turns: int,
    qa_path: Path,
    skip_derive: bool,
    api_pid: int | None,
):
    questions = load_questions(qa_path)
    await _wait_ready(base_url)

    peaks: dict[str, tuple[float, float]] = {}
    proc_peaks: dict[str, float] = {}
    pids: dict[str, int] = {}
    if api_pid is not None:
        pids[API_MEMBER] = api_pid
    stop = asyncio.Event()
    sampler = asyncio.create_task(_sample_memory(peaks, proc_peaks, pids, stop))
    derive_task = None if skip_derive else asyncio.create_task(_run_derive(pids))

    session_results = await asyncio.gather(
        *[_run_session(base_url, s, questions, turns) for s in range(sessions)]
    )
    derive_rc, derive_wall = (0, 0.0) if derive_task is None else await derive_task
    stop.set()
    await sampler

    turns_flat = [t for results in session_results for t in results]
    return summarize(turns_flat), peaks, proc_peaks, derive_rc, derive_wall


def _report(
    summary: dict,
    peaks: dict[str, tuple[float, float]],
    proc_peaks: dict[str, float],
    derive_rc: int,
    derive_wall: float,
    skip: bool,
) -> int:
    print(f"turns={summary['turns']} verdicts={summary['verdicts']}")
    first, turn = summary["first_event_ms"], summary["turn_ms"]
    print(f"first event ms: p50={first['p50']:.0f} p95={first['p95']:.0f}")
    print(f"turn ms: p50={turn['p50']:.0f} p95={turn['p95']:.0f} max={turn['max']:.0f}")
    if not skip:
        print(f"concurrent derive: rc={derive_rc} wall={derive_wall:.1f}s")
    for name, (mib, pct) in sorted(peaks.items()):
        print(f"memory peak {name}: {mib:.0f} MiB ({pct:.1f}%)")
    for label, mib in sorted(proc_peaks.items()):
        print(f"memory peak process:{label}: {mib:.0f} MiB")
    print(
        f"fleet peak: {fleet_total_mib(peaks, proc_peaks):.0f} MiB / {FLEET_MEMORY_BUDGET_MIB} MiB"
    )
    failed = False
    for error in summary["errors"]:
        print(f"TURN FAILED: {error}", file=sys.stderr)
        failed = True
    # A member that was never observed means the budget was not proven — fail
    # closed rather than report a partial sample as a pass.
    for member in missing_members(peaks, proc_peaks, skip_derive=skip):
        print(f"UNOBSERVED MEMBER: {member} was never sampled", file=sys.stderr)
        failed = True
    for alert in memory_alerts(peaks):
        print(f"MEMORY ALERT: {alert}", file=sys.stderr)
        failed = True
    budget_alert = fleet_budget_alert(peaks, proc_peaks)
    if budget_alert is not None:
        print(f"FLEET BUDGET EXCEEDED: {budget_alert}", file=sys.stderr)
        failed = True
    if derive_rc != 0:
        print(f"DERIVE FAILED: rc={derive_rc}", file=sys.stderr)
        failed = True
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=None, help="target a running API instead")
    parser.add_argument(
        "--api-pid",
        type=int,
        default=None,
        help="PID of the external API to sample memory for; required with --api-url so the "
        "API is not left unobserved (the gate fails if the API is never sampled)",
    )
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSIONS)
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS, help="turns per session")
    parser.add_argument("--qa", type=Path, default=DEFAULT_QA, help="question source")
    parser.add_argument("--skip-derive", action="store_true", help="chat load only")
    args = parser.parse_args()

    api_proc = None
    base_url = args.api_url
    api_pid = args.api_pid
    if base_url is None:
        api_proc, base_url = _start_api()
        api_pid = api_proc.pid  # sample the API we started; --api-pid is for external targets
    try:
        summary, peaks, proc_peaks, derive_rc, derive_wall = asyncio.run(
            run_load(base_url, args.sessions, args.turns, args.qa, args.skip_derive, api_pid)
        )
    finally:
        if api_proc is not None:
            api_proc.terminate()
            api_proc.wait(timeout=15)
    return _report(summary, peaks, proc_peaks, derive_rc, derive_wall, args.skip_derive)


if __name__ == "__main__":
    raise SystemExit(main())
