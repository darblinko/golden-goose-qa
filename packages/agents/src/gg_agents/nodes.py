"""Graph nodes. Each node is a small async function on AgentNodes that reads
state, does one job, and returns a partial state update (never mutates).

Grounding rules enforced here:
- Empty scoped retrieval ends in an honest "not in corpus" answer — never an
  unscoped fallback search.
- Generation must cite; the verifier hard-fails any answer without markers,
  allows one corrective regeneration, then downgrades to insufficient evidence.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from gg_common import acl
from gg_common.costs import cost_stage
from gg_common.providers.base import ChatMessage, LLMProvider
from gg_common.settings import AppSettings
from gg_common.tracing import traced
from gg_retrieval.retriever import HybridRetriever
from gg_retrieval.search import AS_OF_TIMELESS_DOC_TYPES
from gg_retrieval.tools.external.models import ExternalResult
from gg_retrieval.tools.external.toolkit import ExternalToolkit
from gg_retrieval.tools.graph_walk import GraphWalker
from gg_retrieval.tools.models import ToolResult
from gg_retrieval.tools.warehouse import WarehouseTool
from langgraph.config import get_stream_writer

from gg_agents import prompts, toolselect
from gg_agents.state import (
    DEFAULT_PATTERN,
    PATTERNS,
    AgentState,
    chunk_to_dict,
    citation_view,
    external_parent_dict,
    parent_to_dict,
    tool_parent_dict,
)

GENERATION_PARENTS = 6

# Doc types that legitimately carry no revision, so the revision-provenance gate
# must not drop them: point-in-time records (complaints, NCRs, CAPAs, ...) are
# facts of their date, not versioned documents, and the synthetic parents that
# wrap structured-tool and external results carry their own attribution.
# training_matrix is excluded from the as-of timeless set (it is versioned), but
# stays revision-exempt here so a matrix without a populated revision is not
# dropped as evidence — its temporal correctness is enforced by the as-of
# effective-interval filter, not by this citation gate.
_REVISION_EXEMPT_DOC_TYPES = AS_OF_TIMELESS_DOC_TYPES | {
    "training_matrix",
    "tool_result",
    "external_result",
}

NO_EVIDENCE_ANSWER = (
    "The document corpus does not contain evidence that answers this question. "
    "No matching effective documents were found within the searched scope."
)
TOOL_FAILURE_ANSWER = (
    "The structured record tools could not answer this question ({reason}). "
    "Try asking about a specific document or record instead (for example a "
    "CAPA, NCR, or SOP by id)."
)
NOT_IN_CORPUS_ANSWER = (
    "The requested item ({anchor}) was not found in the knowledge graph, so "
    "there is no grounded evidence to answer this question. It may not exist "
    "or may not have been ingested."
)
OUT_OF_SCOPE_ANSWER = (
    "I answer questions about this company's quality management system documents: "
    "SOPs, CAPAs, NCRs, complaints, MDRs, FMEAs, traceability, and device history "
    "records. Ask me about one of those."
)
UNSUPPORTED_ANSWER = (
    "The generated answer could not be verified against the retrieved documents, "
    "so it has been withheld. The sources retrieved for this question are listed "
    "for manual review."
)
EXTERNAL_DEGRADED_NOTICE = (
    "\n\nNote: external data sources could not be reached for this question "
    "({error}). This answer is based on internal QMS evidence only and may be "
    "incomplete."
)
COMPARE_INSUFFICIENT_ANSWER = (
    "A rate comparison cannot be supported from the available evidence. A rate "
    "is a numerator over a denominator, and comparing two rates needs a "
    "compatible denominator — the device population the counts are normalized "
    "against — on both sides. The internal registers provide a record count but "
    "no device-population denominator, and the openFDA/MAUDE response provides a "
    "raw match count with no exposure denominator, so an internal rate and the "
    "MAUDE rate cannot be formed or compared. The internal count and the "
    "external total are listed separately for manual review; they are not "
    "comparable as rates and must not be divided."
)

# A fixed internal numerator for the comparison: the complaint record count.
# Constant text (no interpolation); the SQL guard re-validates it before it runs.
_COMPLAINT_COUNT_SQL = "SELECT count(*) AS complaints FROM registers.v_complaint_register"

# Columns that would carry a device-population / exposure denominator if the
# surface exposed one. It does not today, so _rate_denominators returns None and
# the compare path refuses — but the scan is real, so a future population view
# would light up the supported branch without further routing changes.
_POPULATION_COLUMNS = (
    "population",
    "device_population",
    "installed_base",
    "units_shipped",
    "exposure",
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_CITATION_RE = re.compile(r"\[(\d+)\]")


def _emit(event: dict[str, Any]) -> None:
    """Best-effort custom stream event; a no-op outside a streaming run."""
    try:
        writer = get_stream_writer()
    except Exception:
        return
    writer(event)


def _parse_json(text: str) -> dict[str, Any] | None:
    match = _JSON_RE.search(text)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _state_role(state: AgentState) -> str:
    # Fail closed: a turn that never declared a role gets the least access.
    return state.get("role") or "auditor_readonly"


def _retrieval_levels(state: AgentState) -> tuple[str, ...] | None:
    """Access-level filter for retrieval, or None when the role sees all
    levels — unfiltered search also keeps chunks indexed before access
    labeling existed reachable for trusted roles."""
    levels = acl.allowed_access_levels(_state_role(state))
    return None if levels == acl.ACCESS_LEVELS else levels


def _in_scope(item: Any, state: AgentState) -> bool:
    doc_key = state.get("doc_key")
    revision = state.get("revision")
    if doc_key and item.doc_key != doc_key:
        return False
    return not (revision and item.revision != revision)


def _prompt_hash(messages: list[ChatMessage]) -> str:
    material = "\x1e".join(f"{m.role}:{m.content}" for m in messages)
    return hashlib.sha256(material.encode()).hexdigest()


def _first_sentences(text: str, limit: int = 240) -> str:
    clipped = " ".join(text.split())[:limit]
    return clipped


def _has_required_revision(parent: dict[str, Any]) -> bool:
    """Whether a parent may serve as generation evidence under the citation
    contract. Every answer must cite doc id, revision, and page; a controlled
    document whose revision is missing cannot be cited that way, so surfacing it
    would produce an under-scoped, unverifiable audit answer. Fail closed and
    drop it. Point-in-time records and synthetic tool/external parents are
    exempt — they legitimately have no revision. External evidence carries its
    own attribution and is never gated here."""
    if parent.get("provenance") != "internal":
        return True
    if parent.get("doc_type", "") in _REVISION_EXEMPT_DOC_TYPES:
        return True
    return bool((parent.get("revision") or "").strip())


def generation_parents(state: AgentState) -> list[dict[str, Any]]:
    """Evidence handed to generate/verify: internal parents first, external
    evidence appended last so markers for QMS documents stay stable. Controlled
    documents missing a revision are dropped before the window is sliced — an
    answer that cannot cite a revision must not be built on that source."""
    internal = [p for p in state["parents"] if _has_required_revision(p)]
    return internal[:GENERATION_PARENTS] + state.get("external_parents", [])


@dataclass(frozen=True)
class AgentDeps:
    settings: AppSettings
    retriever: HybridRetriever
    llm: LLMProvider
    llm_is_fake: bool = False
    warehouse: WarehouseTool | None = None
    graph: GraphWalker | None = None
    external: ExternalToolkit | None = None


class AgentNodes:
    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps

    @traced("agent.route")
    async def route(self, state: AgentState) -> AgentState:
        as_of = toolselect.extract_as_of(state["question"])
        as_of_iso = as_of.isoformat() if as_of else None
        # Hard document/revision scope is deterministic and independent of the
        # route: it flows into both retrieval channels and is preserved across
        # query rewrites so an explicitly scoped question can never leak a
        # neighboring document or revision.
        scope = toolselect.extract_scope(state["question"])
        override = toolselect.route_override(state["question"])
        if override is not None:
            _emit(
                {
                    "event": "step",
                    "node": "route",
                    "pattern": override,
                    "doc_type": None,
                    "doc_key": scope.doc_key,
                    "revision": scope.revision,
                    "as_of": as_of_iso,
                }
            )
            return {
                "pattern": override,
                "doc_type": None,
                "doc_key": scope.doc_key,
                "revision": scope.revision,
                "as_of": as_of_iso,
            }
        with cost_stage("agent.route"):
            parsed = _parse_json(
                await self.deps.llm.complete(prompts.router_messages(state["question"]))
            )
        pattern = parsed.get("pattern") if parsed else None
        doc_type = parsed.get("doc_type") if parsed else None
        if pattern not in PATTERNS:
            # Unparseable or unknown routing defaults to unfiltered retrieval —
            # the safe direction is to search, not to refuse.
            pattern, doc_type = DEFAULT_PATTERN, None
        _emit(
            {
                "event": "step",
                "node": "route",
                "pattern": pattern,
                "doc_type": doc_type,
                "doc_key": scope.doc_key,
                "revision": scope.revision,
                "as_of": as_of_iso,
            }
        )
        return {
            "pattern": pattern,
            "doc_type": doc_type if isinstance(doc_type, str) else None,
            "doc_key": scope.doc_key,
            "revision": scope.revision,
            "as_of": as_of_iso,
        }

    @traced("agent.retrieve")
    async def retrieve(self, state: AgentState) -> AgentState:
        as_of_iso = state.get("as_of")
        result = await self.deps.retriever.retrieve(
            state["query"],
            doc_type=state.get("doc_type"),
            doc_key=state.get("doc_key"),
            revision=state.get("revision"),
            as_of=date.fromisoformat(as_of_iso) if as_of_iso else None,
            allowed_levels=_retrieval_levels(state),
        )
        # The search filter already applies the scope; dropping anything outside
        # it here keeps an exact-record or exact-revision question from citing a
        # different record when the filter is bypassed or misconfigured. An
        # absent record then ends at no_evidence instead of a neighbour's text.
        chunks = [c for c in result.chunks if _in_scope(c, state)]
        parents = [p for p in result.parents if _in_scope(p, state)]
        _emit(
            {
                "event": "step",
                "node": "retrieve",
                "query": state["query"],
                "n_chunks": len(chunks),
                "n_parents": len(parents),
                "timings_ms": result.timings_ms,
            }
        )
        return {
            "chunks": [chunk_to_dict(c) for c in chunks],
            "parents": [parent_to_dict(p) for p in parents],
        }

    @traced("agent.grade")
    async def grade(self, state: AgentState) -> AgentState:
        parents = state["parents"]
        if not parents:
            _emit({"event": "step", "node": "grade", "sufficient": False, "reason": "no results"})
            return {"grade_sufficient": False, "grade_reason": "no results"}
        with cost_stage("agent.grade"):
            parsed = _parse_json(
                await self.deps.llm.complete(prompts.grader_messages(state["question"], parents))
            )
        if parsed is None or not isinstance(parsed.get("sufficient"), bool):
            # An unreadable grade must not strand the turn: proceed to
            # generation and let the verifier gate the output.
            sufficient, reason = True, "grader response unparseable; proceeding"
        else:
            sufficient, reason = parsed["sufficient"], str(parsed.get("reason", ""))
        _emit({"event": "step", "node": "grade", "sufficient": sufficient, "reason": reason})
        return {"grade_sufficient": sufficient, "grade_reason": reason}

    @traced("agent.rewrite")
    async def rewrite(self, state: AgentState) -> AgentState:
        with cost_stage("agent.rewrite"):
            rewritten = await self.deps.llm.complete(
                prompts.rewriter_messages(state["question"], state["query"], state["grade_reason"])
            )
        query = rewritten.strip().splitlines()[0] if rewritten.strip() else state["question"]
        _emit({"event": "step", "node": "rewrite", "query": query})
        return {"query": query, "rewrites": state["rewrites"] + 1}

    @traced("agent.external")
    async def external(self, state: AgentState) -> AgentState:
        """Fetch external evidence for the question. Failures degrade to an
        internal-only answer — external data is supplementary, never blocking."""
        if self.deps.external is None:
            _emit({"event": "step", "node": "external", "error": "external tools not configured"})
            return {"external_parents": [], "external_error": "external tools not configured"}
        plan = toolselect.external_plan(state["question"])
        try:
            result = await self._run_external(self.deps.external, plan)
        except Exception as exc:
            _emit({"event": "step", "node": "external", "method": plan.method, "error": str(exc)})
            return {"external_parents": [], "external_error": str(exc)}
        _emit(
            {
                "event": "step",
                "node": "external",
                "method": plan.method,
                "query": result.query,
                "n_rows": len(result.rows),
            }
        )
        return {"external_parents": [external_parent_dict(result)]}

    async def _run_external(
        self, toolkit: ExternalToolkit, plan: toolselect.ExternalPlan
    ) -> ExternalResult:
        if plan.method == "maude":
            return await toolkit.openfda.maude_events(plan.term)
        if plan.method == "recalls":
            return await toolkit.openfda.recalls(plan.term)
        if plan.method == "510k":
            return await toolkit.openfda.clearances_510k(plan.term)
        if plan.method == "pma":
            return await toolkit.openfda.pma_approvals(plan.term)
        if plan.method == "gudid":
            return await toolkit.openfda.gudid(plan.term)
        if plan.method == "compliance":
            return await toolkit.openfda.compliance_actions(plan.term)
        if plan.method == "ecfr":
            return await toolkit.ecfr.search_regulations(plan.term)
        if plan.method == "guidance":
            return await toolkit.ecfr.guidance_documents(plan.term)
        if plan.method == "clinicaltrials":
            return await toolkit.clinicaltrials.search(plan.term)
        if plan.method == "pubmed":
            return await toolkit.pubmed.search(plan.term)
        return await toolkit.websearch.search(plan.term)

    @traced("agent.generate")
    async def generate(self, state: AgentState) -> AgentState:
        parents = generation_parents(state)
        messages = prompts.generator_messages(state["question"], parents, state.get("history", []))
        if state.get("regenerated"):
            messages = [
                *messages,
                ChatMessage(
                    role="user",
                    content=(
                        "Your previous answer failed citation verification. Restate it "
                        "with a [n] source marker after every factual claim, or reply "
                        "INSUFFICIENT_EVIDENCE."
                    ),
                ),
            ]
        if self.deps.llm_is_fake:
            answer = self._extractive_answer(parents)
        else:
            with cost_stage("agent.generate"):
                answer = (await self.deps.llm.complete(messages)).strip()
        _emit({"event": "step", "node": "generate", "chars": len(answer)})
        return {"answer": answer, "prompt_hash": _prompt_hash(messages)}

    def _extractive_answer(self, parents: list[dict[str, Any]]) -> str:
        """Deterministic cited quotes when no LLM key is configured. Honest
        about what it is, and exercises the full citation/verification path."""
        if not parents:
            return "INSUFFICIENT_EVIDENCE"
        if parents[0]["doc_type"] == "tool_result":
            # Tool tables are the answer; render them whole, not clipped.
            return f"Structured tool result:\n{parents[0]['text']} [1]"
        lines: list[str] = []
        internal_quoted = 0
        for i, parent in enumerate(parents, start=1):
            if parent["doc_type"] == "external_result":
                # External tables render whole so their banner stays visible.
                lines.append(f"{parent['text']} [{i}]")
            elif internal_quoted < 2:
                lines.append(f'{parent["citation"]}: "{_first_sentences(parent["text"])}" [{i}]')
                internal_quoted += 1
        return "Extractive answer (no LLM configured):\n" + "\n".join(lines)

    @traced("agent.verify")
    async def verify(self, state: AgentState) -> AgentState:
        answer = state["answer"]
        parents = generation_parents(state)
        if answer.strip() == "INSUFFICIENT_EVIDENCE":
            return {
                "verdict": "insufficient_evidence",
                "answer": NO_EVIDENCE_ANSWER,
                "citations": [],
            }

        cited_markers = sorted(
            {int(m) for m in _CITATION_RE.findall(answer) if 1 <= int(m) <= len(parents)}
        )
        if not cited_markers:
            return self._verification_failure(state, "no citation markers in answer")

        cited_pairs = [(m, parents[m - 1]) for m in cited_markers]
        verifier_error: str | None
        if self.deps.llm_is_fake:
            # The fake LLM cannot judge entailment (its completions are opaque
            # hashes). Citation presence was already enforced deterministically
            # above; record the gap honestly instead of pretending it passed.
            verifier_error = "fake llm: entailment not evaluated"
        else:
            with cost_stage("agent.verify"):
                parsed = _parse_json(
                    await self.deps.llm.complete(prompts.verifier_messages(answer, cited_pairs))
                )
            if parsed is None or not isinstance(parsed.get("grounded"), bool):
                # Fail closed: an unreadable verdict is not a pass. One
                # regeneration is allowed, then the answer is withheld.
                return self._verification_failure(state, "verifier response unparseable")
            if not parsed["grounded"]:
                claims = ", ".join(str(c) for c in parsed.get("unsupported_claims", []))
                return self._verification_failure(
                    state, f"unsupported claims: {claims or 'unspecified'}"
                )
            verifier_error = None

        if state.get("external_error"):
            answer = answer + EXTERNAL_DEGRADED_NOTICE.format(error=state["external_error"])
        citations = [citation_view(p, m) for m, p in cited_pairs]
        _emit({"event": "citations", "items": citations})
        _emit({"event": "step", "node": "verify", "verdict": "grounded", "error": verifier_error})
        return {
            "verdict": "grounded",
            "answer": answer,
            "citations": citations,
            "verifier_error": verifier_error,
        }

    def _verification_failure(self, state: AgentState, reason: str) -> AgentState:
        if not state.get("regenerated"):
            _emit({"event": "step", "node": "verify", "verdict": "retry", "reason": reason})
            return {"regenerated": True, "verdict": ""}
        _emit(
            {
                "event": "step",
                "node": "verify",
                "verdict": "insufficient_evidence",
                "reason": reason,
            }
        )
        citations = [citation_view(p, i) for i, p in enumerate(generation_parents(state), start=1)]
        return {
            "verdict": "insufficient_evidence",
            "answer": UNSUPPORTED_ANSWER,
            "citations": citations,
            "verifier_error": reason,
        }

    @traced("agent.no_evidence")
    async def no_evidence(self, state: AgentState) -> AgentState:
        _emit({"event": "step", "node": "no_evidence", "rewrites": state["rewrites"]})
        return {"verdict": "insufficient_evidence", "answer": NO_EVIDENCE_ANSWER, "citations": []}

    @traced("agent.warehouse")
    async def warehouse(self, state: AgentState) -> AgentState:
        if self.deps.warehouse is None:
            return self._tool_failure("warehouse", "record warehouse is not configured")
        plan = toolselect.warehouse_plan(state["question"])
        role = _state_role(state)
        try:
            if plan.saved is not None:
                result = await self.deps.warehouse.run_saved(plan.saved, plan.params, role=role)
            elif plan.sql is not None and plan.title is not None:
                result = await self.deps.warehouse.run_sql(plan.sql, title=plan.title, role=role)
            else:
                return self._tool_failure("warehouse", "no executable warehouse plan")
        except Exception as exc:
            return self._tool_failure("warehouse", str(exc))
        return self._tool_success("warehouse", result)

    @traced("agent.compare")
    async def compare(self, state: AgentState) -> AgentState:
        """Rate-comparison path: pit an internal count against a public source as
        a rate. A rate needs a numerator and a compatible denominator on both
        sides; the register surface exposes no device-population denominator, so
        this refuses with insufficient_evidence rather than dividing counts that
        are not comparable. The internal count and the external total are both
        surfaced as separated evidence for manual review."""
        internal = await self._compare_internal(state)
        external = await self._compare_external(state)
        if _rate_denominators(internal, external) is None:
            return self._compare_insufficient(internal, external)
        # Both populations resolved: hand the two evidence pieces to the
        # generator (internal parent first so its marker stays stable) and let
        # generate/verify produce the comparison.
        _emit({"event": "step", "node": "compare", "verdict": "supported"})
        return {
            "parents": [tool_parent_dict(internal)] if internal is not None else [],
            "external_parents": [external_parent_dict(external)] if external is not None else [],
        }

    async def _compare_internal(self, state: AgentState) -> ToolResult | None:
        if self.deps.warehouse is None:
            _emit({"event": "step", "node": "compare", "error": "warehouse not configured"})
            return None
        try:
            return await self.deps.warehouse.run_sql(
                _COMPLAINT_COUNT_SQL, title="Complaint count", role=_state_role(state)
            )
        except Exception as exc:
            _emit({"event": "step", "node": "compare", "error": f"internal count failed: {exc}"})
            return None

    async def _compare_external(self, state: AgentState) -> ExternalResult | None:
        if self.deps.external is None:
            _emit({"event": "step", "node": "compare", "error": "external tools not configured"})
            return None
        plan = toolselect.external_plan(state["question"])
        try:
            return await self._run_external(self.deps.external, plan)
        except Exception as exc:
            _emit({"event": "step", "node": "compare", "error": f"external lookup failed: {exc}"})
            return None

    def _compare_insufficient(
        self, internal: ToolResult | None, external: ExternalResult | None
    ) -> AgentState:
        parents = [tool_parent_dict(internal)] if internal is not None else []
        external_parents = [external_parent_dict(external)] if external is not None else []
        citations = [
            citation_view(parent, marker)
            for marker, parent in enumerate(parents + external_parents, start=1)
        ]
        _emit({"event": "citations", "items": citations})
        _emit({"event": "step", "node": "compare", "verdict": "insufficient_evidence"})
        return {
            "verdict": "insufficient_evidence",
            "answer": COMPARE_INSUFFICIENT_ANSWER,
            "citations": citations,
            "parents": parents,
            "external_parents": external_parents,
        }

    @traced("agent.graph_walk")
    async def graph_walk(self, state: AgentState) -> AgentState:
        if self.deps.graph is None:
            return self._tool_failure("graph_walk", "knowledge graph is not configured")
        if state.get("as_of"):
            # The graph is rebuilt from the current corpus and carries no
            # validity windows, so a traversal can only describe today.
            return self._tool_failure(
                "graph_walk",
                f"as-of {state['as_of']} was requested, and knowledge graph traversals "
                "describe only the current corpus",
            )
        plan = toolselect.graph_plan(state["question"])
        anchor = plan.argument or ""
        if (
            anchor
            and acl.is_restricted_key(anchor)
            and not acl.can_read_restricted(_state_role(state))
        ):
            return self._tool_failure(
                "graph_walk", "complaint and MDR records require the qa_user or admin role"
            )
        try:
            if plan.method == "requirement_trace":
                result = await self.deps.graph.requirement_trace(plan.argument or "")
            elif plan.method == "training_status":
                result = await self.deps.graph.training_status(plan.argument or "")
            elif plan.method == "record_thread":
                result = await self.deps.graph.record_thread(plan.argument or "")
            elif plan.method == "document_profile":
                result = await self.deps.graph.document_profile(plan.argument or "")
            else:
                result = await self.deps.graph.unverified_requirements()
        except Exception as exc:
            return self._tool_failure("graph_walk", str(exc))
        return self._tool_success("graph_walk", result)

    def _tool_success(self, node: str, result: ToolResult) -> AgentState:
        _emit(
            {
                "event": "step",
                "node": node,
                "query": result.query,
                "n_rows": len(result.rows),
                "truncated": result.truncated,
            }
        )
        if result.anchor_missing:
            # The lookup addressed an entity that is not in the corpus. Do not
            # hand its "(no matching rows)" table to the generator as evidence —
            # answer "not in corpus" honestly instead of citing an empty table.
            _emit({"event": "step", "node": node, "verdict": "insufficient_evidence"})
            return {
                "verdict": "insufficient_evidence",
                "answer": NOT_IN_CORPUS_ANSWER.format(anchor=result.title),
                "citations": [],
                "verifier_error": "anchor not found in corpus",
            }
        return {"parents": [tool_parent_dict(result)]}

    def _tool_failure(self, node: str, reason: str) -> AgentState:
        _emit({"event": "step", "node": node, "error": reason})
        return {
            "verdict": "insufficient_evidence",
            "answer": TOOL_FAILURE_ANSWER.format(reason=reason),
            "citations": [],
            "verifier_error": reason,
        }

    @traced("agent.out_of_scope")
    async def out_of_scope(self, state: AgentState) -> AgentState:
        return {"verdict": "not_applicable", "answer": OUT_OF_SCOPE_ANSWER, "citations": []}


def _rate_denominators(
    internal: ToolResult | None, external: ExternalResult | None
) -> tuple[int, int] | None:
    """The (internal, external) device-population denominators a rate comparison
    needs, or None when either is missing. Both results carry raw counts, not the
    population they would be normalized against; the register surface and openFDA
    responses do not expose one today, so this returns None and the compare path
    refuses instead of dividing incomparable counts."""
    internal_population = _population_in_rows(internal.rows if internal is not None else ())
    external_population = _population_in_rows(external.rows if external is not None else ())
    if internal_population is None or external_population is None:
        return None
    return internal_population, external_population


def _population_in_rows(rows: tuple[dict[str, Any], ...]) -> int | None:
    for row in rows:
        for column in _POPULATION_COLUMNS:
            value = row.get(column)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
    return None
