"use client";

import type { TraceEvent } from "@/lib/types";

const NODE_LABELS: Record<string, string> = {
  route: "Classifying the question",
  retrieve: "Searching the corpus",
  grade: "Grading the evidence",
  rewrite: "Refining the query",
  generate: "Drafting the answer",
  verify: "Verifying citations",
  no_evidence: "No supporting evidence found",
};

function describe(step: TraceEvent): string {
  const node = typeof step.node === "string" ? step.node : "";
  const base = NODE_LABELS[node] ?? node;
  if (node === "route" && typeof step.pattern === "string") {
    return `${base} — ${step.pattern}`;
  }
  if (node === "retrieve" && typeof step.n_parents === "number") {
    return `${base} — ${step.n_parents} documents`;
  }
  if (node === "grade" && typeof step.sufficient === "boolean") {
    return `${base} — ${step.sufficient ? "sufficient" : "insufficient"}`;
  }
  if (node === "verify" && typeof step.verdict === "string") {
    return `${base} — ${step.verdict}`;
  }
  return base;
}

export default function StepTrace({
  steps,
  live = false,
}: {
  steps: TraceEvent[];
  live?: boolean;
}) {
  const stepEvents = steps.filter((step) => step.event === "step");
  return (
    <div className="step-trace">
      {stepEvents.map((step, index) => (
        <div
          key={index}
          className={`step-line${live && index === stepEvents.length - 1 ? " live" : ""}`}
        >
          <span className="dot" />
          <span>{describe(step)}</span>
        </div>
      ))}
      {live && stepEvents.length === 0 ? (
        <div className="step-line live">
          <span className="dot" />
          <span>Starting…</span>
        </div>
      ) : null}
    </div>
  );
}
