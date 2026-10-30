"use client";

import { type FormEvent, useCallback, useRef, useState } from "react";
import { API_URL, ApiError, getTrace } from "@/lib/api";
import { KIND_GROUPS } from "@/lib/traceStyle";
import type { TraceGraph as TraceGraphData } from "@/lib/types";
import TraceGraph from "./TraceGraph";
import TraceNodePanel from "./TraceNodePanel";

interface Notice {
  title: string;
  detail: string;
}

const LABELS =
  "Document, DocumentRevision, Requirement, DesignOutput, Supplier, Person or FmeaRow";

function failureNotice(err: unknown, anchor: string): Notice {
  if (!(err instanceof ApiError)) {
    return {
      title: "The API did not respond.",
      detail: `Check that the API is running at ${API_URL}, then trace again.`,
    };
  }
  switch (err.status) {
    case 401:
      return {
        title: "The session has expired.",
        detail: "Sign out and sign in again, then trace again.",
      };
    case 403:
      return {
        title: "This role cannot open the trace view.",
        detail:
          "Trace is available to QA users and admins. Sign in with one of those roles.",
      };
    case 404:
      return {
        title: `No record has the ID ${anchor}.`,
        detail:
          "Check the ID. A bare ID is read as a document key; for any other " +
          `record, prefix its label, for example Requirement:REQ-014. Labels: ${LABELS}.`,
      };
    case 422:
      return {
        title: `${anchor} is not a valid record ID.`,
        detail:
          "Use up to 80 letters, digits, spaces, periods, underscores, slashes, " +
          `colons and hyphens, optionally prefixed with a label (${LABELS}) and a colon.`,
      };
    default:
      return {
        title: "The trace request failed.",
        detail: `The API returned ${err.status}: ${err.message}.`,
      };
  }
}

function Counts({ graph }: { graph: TraceGraphData }) {
  const inferred = graph.edges.filter((edge) => edge.inferred).length;
  const hidden = graph.nodes.reduce((sum, node) => sum + node.hidden_links, 0);
  const items = [
    { value: graph.nodes.length, label: "nodes" },
    { value: graph.edges.length, label: "links" },
    { value: graph.edges.length - inferred, label: "recorded" },
    { value: inferred, label: "inferred" },
    { value: hidden, label: "hidden links" },
  ];
  return (
    <div className="trace-counts">
      {items.map((item) => (
        <div key={item.label} className="trace-count">
          <span className="trace-count-value">{item.value}</span>
          <span className="trace-count-label">{item.label}</span>
        </div>
      ))}
      {graph.truncated && (
        <p className="trace-truncated">
          Expansion caps removed some records or links. Centre on a record to
          see more of its neighbourhood.
        </p>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="trace-legend">
      <span className="trace-legend-item">
        <svg width="26" height="8" aria-hidden="true">
          <line className="trace-legend-line" x1="1" y1="4" x2="25" y2="4" />
        </svg>
        Recorded field
      </span>
      <span className="trace-legend-item">
        <svg width="26" height="8" aria-hidden="true">
          <line className="trace-legend-line inferred" x1="1" y1="4" x2="25" y2="4" />
        </svg>
        Mined from text
      </span>
      {KIND_GROUPS.map(({ group, label }) => (
        <span key={group} className={`trace-legend-item kind-${group}`}>
          <span className="trace-swatch" aria-hidden="true" />
          {label}
        </span>
      ))}
    </div>
  );
}

function StateMessage({ title, detail }: Notice) {
  return (
    <div className="trace-state">
      <h2>{title}</h2>
      <p>{detail}</p>
    </div>
  );
}

const INTRO: Notice = {
  title: "Trace a record through the knowledge graph.",
  detail:
    "Enter a record ID to draw the record, the records it links to, and the " +
    "records linked to those. Solid lines are links read from a structured " +
    "field; dashed lines are links mined from free text. Select a node to " +
    "see where each link was read.",
};

/** Fetch state for the trace view. A response that arrives after a newer
 * request was made is dropped. */
function useTraceRequest() {
  const [graph, setGraph] = useState<TraceGraphData | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const requestId = useRef(0);

  const trace = useCallback(async (anchor: string) => {
    const current = ++requestId.current;
    setPending(anchor);
    setNotice(null);
    try {
      const result = await getTrace(anchor);
      if (current === requestId.current) setGraph(result);
    } catch (err) {
      if (current !== requestId.current) return;
      setGraph(null);
      setNotice(failureNotice(err, anchor));
    } finally {
      if (current === requestId.current) setPending(null);
    }
  }, []);

  return { graph, pending, notice, trace };
}

function TraceBody({
  graph,
  pending,
  notice,
  selectedId,
  onSelect,
}: {
  graph: TraceGraphData | null;
  pending: string | null;
  notice: Notice | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (pending) {
    return (
      <StateMessage
        title={`Tracing ${pending}.`}
        detail="Reading the record and its links from the knowledge graph."
      />
    );
  }
  if (notice) return <StateMessage {...notice} />;
  if (!graph) return <StateMessage {...INTRO} />;
  const anchorKey =
    graph.nodes.find((node) => node.id === graph.anchor)?.key ?? graph.anchor;
  return (
    <>
      {graph.edges.length === 0 && (
        <p className="trace-note">
          {anchorKey} has no links in the knowledge graph.
        </p>
      )}
      <TraceGraph graph={graph} selectedId={selectedId} onSelect={onSelect} />
    </>
  );
}

/** The selected node, or the anchor when nothing is selected. */
function panelNode(graph: TraceGraphData | null, selectedId: string | null) {
  if (!graph) return null;
  const find = (id: string | null) => graph.nodes.find((node) => node.id === id);
  return find(selectedId) ?? find(graph.anchor) ?? null;
}

/** A Document id as its bare key when the API reads that key back as a Document. */
function anchorDraft(id: string): string {
  const documentPrefix = "Document:";
  if (!id.startsWith(documentPrefix)) return id;
  const key = id.slice(documentPrefix.length);
  return /^[A-Za-z]+:/.test(key) ? id : key;
}

function AnchorForm({
  draft,
  busy,
  onDraftChange,
  onSubmit,
}: {
  draft: string;
  busy: boolean;
  onDraftChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <form className="trace-form" onSubmit={onSubmit}>
      <h1 className="trace-heading">Trace</h1>
      <input
        className="trace-input"
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
        placeholder="Record ID, for example CAPA-2025-014"
        aria-label="Record ID"
        maxLength={120}
      />
      <button className="btn-primary" type="submit" disabled={busy}>
        {busy ? "Tracing" : "Trace"}
      </button>
    </form>
  );
}

export default function TraceView() {
  const [draft, setDraft] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { graph, pending, notice, trace } = useTraceRequest();

  const start = (anchor: string) => {
    setSelectedId(null);
    void trace(anchor);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const anchor = draft.trim();
    if (anchor) start(anchor);
  };

  const recentre = (id: string) => {
    setDraft(anchorDraft(id));
    start(id);
  };

  return (
    <>
      <div className="trace-col">
        <AnchorForm
          draft={draft}
          busy={pending !== null}
          onDraftChange={setDraft}
          onSubmit={submit}
        />
        {graph && !pending && <Counts graph={graph} />}
        <Legend />
        <TraceBody
          graph={graph}
          pending={pending}
          notice={notice}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
      </div>
      <TraceNodePanel
        graph={pending ? null : graph}
        node={pending ? null : panelNode(graph, selectedId)}
        onSelect={setSelectedId}
        onRecentre={recentre}
      />
    </>
  );
}
