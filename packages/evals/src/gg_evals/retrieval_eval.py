"""Retrieval eval: run golden QA questions through the retriever and score
ranked doc keys against evidence.

Items whose evidence cannot be retrieved by the current slice (aggregate
pseudo-ids, row-level ids, deferred document types) are excluded up front and
reported loudly — a skipped question must never inflate the score.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from gg_retrieval.retriever import HybridRetriever
from pydantic import BaseModel

from gg_evals.metrics import mrr_at_k, ndcg_at_k, recall_at_k

K = 10

# Evidence ids the retrieval index cannot contain, with the reason they are
# excluded (surfaced in the report, never silently dropped). TRN-100 and
# ASL-100 gained parsers in Phase 3 and are now ordinary retrievable docs.
_UNRETRIEVABLE_PREFIXES: dict[str, str] = {
    "corpus:": "aggregate pseudo-id (answered by the record warehouse, not retrieval)",
    "REQ-": "row-level id inside TM-100, not a document",
}

_DOC_KEY_RE = re.compile(r"^[A-Z]{1,6}-[A-Z0-9-]+$")


class EvalItem(BaseModel):
    id: str
    question: str
    pattern: str
    evidence_doc_ids: list[str] = []
    answer_source_ids: list[str] = []  # registers / TM-100 rows: not retrievable
    expected_routes: list[str] = []  # routes that can answer this item (generator-emitted)
    # Doc keys (or "DOC-KEY@REVISION") that must never appear in the ranked
    # results for this scoped question — an obsolete revision, a neighbor outside
    # the filter. Any hit is a non-leakage violation and is release-blocking.
    must_exclude: list[str] = []
    # Expected revision per evidence doc, used for exact-revision citation
    # scoring in the answer eval. Empty leaves scoring at doc-key granularity.
    evidence_revisions: dict[str, str] = {}
    # The golden answer. The answer eval reads the stated count from it for
    # counts_aggregates items; other patterns do not use it yet.
    answer: str = ""
    smoke: bool = False


@dataclass(frozen=True)
class ItemResult:
    item_id: str
    pattern: str
    question: str
    relevant: tuple[str, ...]
    ranked: tuple[str, ...]
    recall: float
    mrr: float
    ndcg: float
    leaked: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalReport:
    results: tuple[ItemResult, ...]
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def recall(self) -> float:
        return _mean([r.recall for r in self.results])

    @property
    def mrr(self) -> float:
        return _mean([r.mrr for r in self.results])

    @property
    def ndcg(self) -> float:
        return _mean([r.ndcg for r in self.results])

    @property
    def leaks(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """(item_id, leaked_ids) for every item whose ranked results surfaced a
        must-exclude document or revision. A non-empty result is a non-leakage
        violation, gated as release-blocking regardless of recall."""
        return tuple((r.item_id, r.leaked) for r in self.results if r.leaked)

    def by_pattern(self) -> dict[str, dict[str, float]]:
        patterns: dict[str, list[ItemResult]] = {}
        for result in self.results:
            patterns.setdefault(result.pattern, []).append(result)
        return {
            pattern: {
                "n": float(len(results)),
                "recall": _mean([r.recall for r in results]),
                "mrr": _mean([r.mrr for r in results]),
            }
            for pattern, results in sorted(patterns.items())
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "n_items": len(self.results),
            "n_skipped": len(self.skipped),
            f"recall@{K}": round(self.recall, 4),
            f"mrr@{K}": round(self.mrr, 4),
            f"ndcg@{K}": round(self.ndcg, 4),
            "by_pattern": self.by_pattern(),
            "leaks": {item_id: list(leaked) for item_id, leaked in self.leaks},
            "skipped": self.skipped,
        }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def retrievable_evidence(evidence_doc_ids: list[str]) -> tuple[list[str], str | None]:
    """Split evidence into retrievable doc keys; reason if nothing remains."""
    docs: list[str] = []
    reasons: list[str] = []
    for evidence_id in evidence_doc_ids:
        prefix_reason = next(
            (r for p, r in _UNRETRIEVABLE_PREFIXES.items() if evidence_id.startswith(p)), None
        )
        if prefix_reason is not None:
            reasons.append(f"{evidence_id}: {prefix_reason}")
            continue
        if not _DOC_KEY_RE.match(evidence_id):
            reasons.append(f"{evidence_id}: not a document key")
            continue
        docs.append(evidence_id)
    if docs:
        return docs, None
    if not evidence_doc_ids:
        return [], "no document evidence (answered from the record warehouse, not retrieval)"
    return [], "; ".join(reasons) or "no evidence ids"


def select_items(
    items: list[EvalItem], *, smoke_only: bool
) -> tuple[list[EvalItem], dict[str, str]]:
    selected: list[EvalItem] = []
    skipped: dict[str, str] = {}
    for item in items:
        if smoke_only and not item.smoke:
            continue
        _, skip_reason = retrievable_evidence(item.evidence_doc_ids)
        if skip_reason is not None:
            skipped[item.id] = skip_reason
            continue
        selected.append(item)
    return selected, skipped


def ranked_doc_keys(chunks_doc_keys: list[str]) -> list[str]:
    """Deduplicate to first (best-ranked) occurrence per document."""
    seen: set[str] = set()
    ranked: list[str] = []
    for doc_key in chunks_doc_keys:
        if doc_key not in seen:
            seen.add(doc_key)
            ranked.append(doc_key)
    return ranked


def detect_leaks(chunks: Iterable[object], must_exclude: list[str]) -> tuple[str, ...]:
    """must-exclude identifiers that actually surfaced in the ranked chunks. An
    entry is either a bare doc key (the whole document must not appear) or
    "DOC-KEY@REVISION" (that exact revision must not appear). Revision-qualified
    entries need the chunk's revision, which stub chunks may omit — treated as
    absent, never a false leak."""
    if not must_exclude:
        return ()
    chunk_list = list(chunks)
    present_keys = {getattr(c, "doc_key", None) for c in chunk_list}
    present_pairs = {
        (getattr(c, "doc_key", None), getattr(c, "revision", None)) for c in chunk_list
    }
    leaked: list[str] = []
    for entry in must_exclude:
        if "@" in entry:
            key, _, revision = entry.partition("@")
            if (key, revision) in present_pairs:
                leaked.append(entry)
        elif entry in present_keys:
            leaked.append(entry)
    return tuple(leaked)


async def evaluate(
    retriever: HybridRetriever, items: list[EvalItem], *, smoke_only: bool = False
) -> EvalReport:
    selected, skipped = select_items(items, smoke_only=smoke_only)
    results = []
    for item in selected:
        relevant, _ = retrievable_evidence(item.evidence_doc_ids)
        result = await retriever.retrieve(item.question, top_k=K)
        ranked = ranked_doc_keys([c.doc_key for c in result.chunks])
        results.append(
            ItemResult(
                item_id=item.id,
                pattern=item.pattern,
                question=item.question,
                relevant=tuple(relevant),
                ranked=tuple(ranked),
                recall=recall_at_k(ranked, set(relevant), K),
                mrr=mrr_at_k(ranked, set(relevant), K),
                ndcg=ndcg_at_k(ranked, set(relevant), K),
                leaked=detect_leaks(result.chunks, item.must_exclude),
            )
        )
    return EvalReport(results=tuple(results), skipped=skipped)
