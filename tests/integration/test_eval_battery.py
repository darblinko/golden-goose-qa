"""The full eval battery against the live fleet: retrieval, end-to-end
answers through the agent graph, routing, and noise sensitivity must all
clear their gates on the smoke set — the same bar the nightly run enforces."""

import json
from pathlib import Path

import pytest
from gg_common.settings import get_settings
from gg_evals.battery import run_battery
from gg_evals.cli import load_items

pytestmark = pytest.mark.integration


async def test_smoke_battery_clears_all_gates(corpus_root: Path, derived_corpus):
    # QA comes from the session-generated corpus, not the gitignored data/
    # directory — CI runners have no pre-generated corpus.
    qa_path = corpus_root / "qa" / "smoke_qa.json"
    report = await run_battery(get_settings(), load_items(qa_path), smoke_only=True)

    assert report.retrieval.results, "no retrieval items were scored"
    assert report.answers.results, "no answers were scored"
    assert report.routing.results, "no routing items were scored"
    assert report.noise.results, "no noise items were scored"
    assert report.passed, f"gates failed: {report.failures}"

    # The report must survive JSON serialization — history and CI artifacts
    # depend on it.
    payload = json.loads(json.dumps(report.as_dict()))
    assert payload["failures"] == []
    assert payload["answers"]["grounded_rate"] >= 0.8
